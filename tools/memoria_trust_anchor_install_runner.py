#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import os
import secrets
import stat
from pathlib import Path
from typing import Any, Callable

from memoria_trust_anchor_authorization import (
    TrustAnchorAuthorizationStore,
)
from memoria_trust_anchor_plan import (
    DEFAULT_SIGNATURE,
    DEFAULT_SOURCE,
    DEFAULT_SUMS,
    DEFAULT_TARGET,
    EXPECTED_FINGERPRINT,
    EXPECTED_SOURCE_SHA256,
    REQUIRED_TARGET_GID,
    REQUIRED_TARGET_MODE,
    REQUIRED_TARGET_UID,
    build_trust_anchor_plan,
    verify_trust_anchor_plan_identity,
)


SCHEMA_VERSION = (
    "memoria-trust-anchor-install-runner-v0.1"
)

MAX_TRUST_ANCHOR_BYTES = 1024 * 1024

SignatureVerifier = Callable[
    [Path, Path, Path],
    tuple[bool, str | None, str | None],
]


def _build_plan(
    *,
    source: Path,
    signature: Path,
    sums: Path,
    target: Path,
    expected_source_sha256: str,
    expected_fingerprint: str,
    signature_verifier: SignatureVerifier | None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "source": source,
        "signature": signature,
        "sums": sums,
        "target": target,
        "expected_source_sha256": (
            expected_source_sha256
        ),
        "expected_fingerprint": expected_fingerprint,
    }

    if signature_verifier is not None:
        kwargs["signature_verifier"] = (
            signature_verifier
        )

    return build_trust_anchor_plan(**kwargs)


def _blocked(reason: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "runner_status": "BLOCKED",
        "authorization_consumed": False,
        "execution_authorized": False,
        "execution_performed": False,
        "filesystem_write_attempted": False,
        "pending_written": False,
        "publish_performed": False,
        "final_verified": False,
        "plan_sha256": None,
        "approval_id": None,
        "target_path": None,
        "reason": reason,
    }


def _verify_target_directory(
    target: Path,
) -> tuple[bool, str | None]:
    parent = target.parent

    if parent.is_symlink():
        return False, "Target directory is a symlink."

    try:
        metadata = parent.lstat()
    except OSError as exc:
        return (
            False,
            "Target directory cannot be inspected: "
            f"{type(exc).__name__}.",
        )

    if not stat.S_ISDIR(metadata.st_mode):
        return False, "Target parent is not a directory."

    if (
        metadata.st_uid != 0
        or metadata.st_gid != 0
    ):
        return (
            False,
            "Target directory is not owned by root:root.",
        )

    if stat.S_IMODE(metadata.st_mode) & 0o022:
        return (
            False,
            "Target directory is group/world writable.",
        )

    return True, None


def _open_verified_directory(
    directory: Path,
) -> int:
    flags = (
        os.O_RDONLY
        | os.O_DIRECTORY
        | os.O_NOFOLLOW
    )

    fd = os.open(directory, flags)

    try:
        metadata = os.fstat(fd)

        if not stat.S_ISDIR(metadata.st_mode):
            raise ValueError(
                "opened target parent is not a directory"
            )

        if (
            metadata.st_uid != 0
            or metadata.st_gid != 0
        ):
            raise ValueError(
                "opened target parent is not root:root"
            )

        if stat.S_IMODE(metadata.st_mode) & 0o022:
            raise ValueError(
                "opened target parent is group/world writable"
            )

        return fd

    except Exception:
        os.close(fd)
        raise


def _read_verified_regular_file(
    path: Path,
    expected_sha256: str,
) -> bytes:
    fd = os.open(
        path,
        os.O_RDONLY | os.O_NOFOLLOW,
    )

    try:
        metadata = os.fstat(fd)

        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError(
                "trust-anchor source is not a regular file"
            )

        digest = hashlib.sha256()
        chunks: list[bytes] = []
        total = 0

        while True:
            chunk = os.read(fd, 64 * 1024)

            if not chunk:
                break

            total += len(chunk)

            if total > MAX_TRUST_ANCHOR_BYTES:
                raise ValueError(
                    "trust-anchor source exceeds size limit"
                )

            digest.update(chunk)
            chunks.append(chunk)

    finally:
        os.close(fd)

    if digest.hexdigest() != expected_sha256:
        raise ValueError(
            "trust-anchor source SHA-256 drift"
        )

    return b"".join(chunks)


def _write_all(
    fd: int,
    payload: bytes,
) -> None:
    offset = 0

    while offset < len(payload):
        written = os.write(
            fd,
            payload[offset:],
        )

        if written <= 0:
            raise OSError(
                "short write while creating pending anchor"
            )

        offset += written


def _pending_metadata_ok(
    path: Path,
) -> bool:
    if path.is_symlink():
        return False

    metadata = path.lstat()

    return bool(
        stat.S_ISREG(metadata.st_mode)
        and stat.S_IMODE(metadata.st_mode)
        == REQUIRED_TARGET_MODE
        and metadata.st_uid == REQUIRED_TARGET_UID
        and metadata.st_gid == REQUIRED_TARGET_GID
    )


def run_trust_anchor_install_attempt(
    store: TrustAnchorAuthorizationStore,
    authorization: dict[str, Any],
    *,
    source: Path = DEFAULT_SOURCE,
    signature: Path = DEFAULT_SIGNATURE,
    sums: Path = DEFAULT_SUMS,
    target: Path = DEFAULT_TARGET,
    expected_source_sha256: str = (
        EXPECTED_SOURCE_SHA256
    ),
    expected_fingerprint: str = (
        EXPECTED_FINGERPRINT
    ),
    signature_verifier: SignatureVerifier | None = None,
) -> tuple[int, dict[str, Any]]:
    """
    Perform exactly one authorized Trust Anchor install attempt.

    No CLI entry point exists here.
    No automatic retry is allowed.
    """

    result = _blocked(
        "Trust Anchor install attempt has not run."
    )
    result["target_path"] = str(target)

    if os.geteuid() != 0:
        result["reason"] = (
            "Trust Anchor installation requires root."
        )
        return 4, result

    directory_ok, directory_reason = (
        _verify_target_directory(target)
    )

    if directory_ok is not True:
        result["reason"] = directory_reason
        return 4, result

    try:
        initial_plan = _build_plan(
            source=source,
            signature=signature,
            sums=sums,
            target=target,
            expected_source_sha256=(
                expected_source_sha256
            ),
            expected_fingerprint=(
                expected_fingerprint
            ),
            signature_verifier=(
                signature_verifier
            ),
        )
    except Exception as exc:
        result["reason"] = (
            "Initial Trust Anchor plan failed: "
            f"{type(exc).__name__}."
        )
        return 5, result

    result["plan_sha256"] = initial_plan.get(
        "plan_sha256"
    )

    # Rebuild immediately before authorization consumption.
    # Drift here must revoke/block the old authorization.
    try:
        consume_plan = _build_plan(
            source=source,
            signature=signature,
            sums=sums,
            target=target,
            expected_source_sha256=(
                expected_source_sha256
            ),
            expected_fingerprint=(
                expected_fingerprint
            ),
            signature_verifier=(
                signature_verifier
            ),
        )
    except Exception as exc:
        result["reason"] = (
            "Pre-consume Trust Anchor plan failed: "
            f"{type(exc).__name__}."
        )
        return 5, result

    allowed, consumed = store.verify_and_consume(
        authorization,
        consume_plan,
    )

    result["authorization_consumed"] = (
        consumed.get("consumed") is True
    )
    result["approval_id"] = consumed.get(
        "approval_id"
    )
    result["plan_sha256"] = consume_plan.get(
        "plan_sha256"
    )

    if allowed is not True:
        result["reason"] = consumed.get(
            "reason",
            "One-shot authorization rejected.",
        )
        return 5, result

    result["execution_authorized"] = True

    # One final read-only plan directly before writing.
    try:
        prewrite_plan = _build_plan(
            source=source,
            signature=signature,
            sums=sums,
            target=target,
            expected_source_sha256=(
                expected_source_sha256
            ),
            expected_fingerprint=(
                expected_fingerprint
            ),
            signature_verifier=(
                signature_verifier
            ),
        )
    except Exception as exc:
        result["runner_status"] = (
            "BLOCKED AFTER CONSUME"
        )
        result["reason"] = (
            "Final pre-write plan failed: "
            f"{type(exc).__name__}. "
            "Authorization remains consumed."
        )
        return 6, result

    if (
        not verify_trust_anchor_plan_identity(
            prewrite_plan
        )
        or prewrite_plan.get("plan_status")
        != "READY FOR APPROVAL"
        or prewrite_plan.get("target_state")
        != "ABSENT"
        or prewrite_plan.get("plan_sha256")
        != consumed.get("plan_sha256")
    ):
        result["runner_status"] = (
            "BLOCKED AFTER CONSUME"
        )
        result["reason"] = (
            "Trust Anchor plan drifted after "
            "authorization consumption."
        )
        return 6, result

    try:
        source_bytes = _read_verified_regular_file(
            source,
            expected_source_sha256,
        )
    except Exception as exc:
        result["runner_status"] = (
            "BLOCKED AFTER CONSUME"
        )
        result["reason"] = (
            "Verified source could not be read: "
            f"{type(exc).__name__}. "
            "Authorization remains consumed."
        )
        return 6, result

    dir_fd: int | None = None
    pending_name: str | None = None
    pending_created = False

    try:
        dir_fd = _open_verified_directory(
            target.parent
        )

        pending_name = (
            target.name
            + "."
            + secrets.token_hex(12)
            + ".pending"
        )

        result["filesystem_write_attempted"] = True
        result["execution_performed"] = True

        pending_fd = os.open(
            pending_name,
            (
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | os.O_NOFOLLOW
            ),
            0o600,
            dir_fd=dir_fd,
        )

        pending_created = True

        try:
            _write_all(
                pending_fd,
                source_bytes,
            )

            os.fchown(
                pending_fd,
                REQUIRED_TARGET_UID,
                REQUIRED_TARGET_GID,
            )
            os.fchmod(
                pending_fd,
                REQUIRED_TARGET_MODE,
            )
            os.fsync(pending_fd)

            metadata = os.fstat(pending_fd)

            if (
                not stat.S_ISREG(metadata.st_mode)
                or stat.S_IMODE(metadata.st_mode)
                != REQUIRED_TARGET_MODE
                or metadata.st_uid
                != REQUIRED_TARGET_UID
                or metadata.st_gid
                != REQUIRED_TARGET_GID
            ):
                raise ValueError(
                    "pending Trust Anchor metadata mismatch"
                )

        finally:
            os.close(pending_fd)

        pending_path = (
            target.parent / pending_name
        )

        if not _pending_metadata_ok(
            pending_path
        ):
            raise ValueError(
                "pending Trust Anchor metadata verification failed"
            )

        pending_sha256 = hashlib.sha256(
            pending_path.read_bytes()
        ).hexdigest()

        if pending_sha256 != expected_source_sha256:
            raise ValueError(
                "pending Trust Anchor SHA-256 mismatch"
            )

        # Verify the pending keyring itself with the signed
        # SHA256SUMS before exposing the final name.
        pending_plan = _build_plan(
            source=pending_path,
            signature=signature,
            sums=sums,
            target=target,
            expected_source_sha256=(
                expected_source_sha256
            ),
            expected_fingerprint=(
                expected_fingerprint
            ),
            signature_verifier=(
                signature_verifier
            ),
        )

        if (
            pending_plan.get("plan_status")
            != "READY FOR APPROVAL"
            or pending_plan.get("target_state")
            != "ABSENT"
            or pending_plan.get(
                "source_fingerprint"
            )
            != expected_fingerprint
        ):
            raise ValueError(
                "pending Trust Anchor verification failed"
            )

        result["pending_written"] = True

        try:
            # Atomic publish with NO replacement.
            os.link(
                pending_name,
                target.name,
                src_dir_fd=dir_fd,
                dst_dir_fd=dir_fd,
                follow_symlinks=False,
            )
        except FileExistsError:
            result["runner_status"] = (
                "BLOCKED AFTER CONSUME"
            )
            result["reason"] = (
                "Final target appeared before publish. "
                "Existing target was not overwritten. "
                "Authorization remains consumed."
            )
            return 7, result

        result["publish_performed"] = True

        os.unlink(
            pending_name,
            dir_fd=dir_fd,
        )
        pending_created = False

        os.fsync(dir_fd)

        # Verify using the INSTALLED keyring itself.
        final_plan = _build_plan(
            source=target,
            signature=signature,
            sums=sums,
            target=target,
            expected_source_sha256=(
                expected_source_sha256
            ),
            expected_fingerprint=(
                expected_fingerprint
            ),
            signature_verifier=(
                signature_verifier
            ),
        )

        if (
            final_plan.get("plan_status")
            != "ALREADY INSTALLED"
            or final_plan.get("target_state")
            != "ALREADY INSTALLED"
            or final_plan.get("source_sha256")
            != expected_source_sha256
            or final_plan.get("target_sha256")
            != expected_source_sha256
            or final_plan.get("source_fingerprint")
            != expected_fingerprint
            or final_plan.get("target_mode")
            != f"{REQUIRED_TARGET_MODE:04o}"
            or final_plan.get("target_uid")
            != REQUIRED_TARGET_UID
            or final_plan.get("target_gid")
            != REQUIRED_TARGET_GID
        ):
            result["runner_status"] = (
                "POST-VERIFY FAILED"
            )
            result["reason"] = (
                "Installed Trust Anchor failed final "
                "cryptographic or metadata verification. "
                "No automatic rollback or retry is allowed."
            )
            return 8, result

        result["final_verified"] = True
        result["runner_status"] = (
            "INSTALL COMPLETED"
        )
        result["reason"] = (
            "Trust Anchor installed and verified. "
            "One-shot authorization is consumed."
        )

        return 0, result

    except Exception as exc:
        result["runner_status"] = "EXECUTION ERROR"
        result["reason"] = (
            "Trust Anchor filesystem attempt failed: "
            f"{type(exc).__name__}. "
            "Authorization remains consumed; "
            "no automatic retry is allowed."
        )
        return 11, result

    finally:
        if (
            dir_fd is not None
            and pending_created
            and pending_name is not None
        ):
            try:
                os.unlink(
                    pending_name,
                    dir_fd=dir_fd,
                )
            except FileNotFoundError:
                pass
            except OSError:
                pass

        if dir_fd is not None:
            os.close(dir_fd)
