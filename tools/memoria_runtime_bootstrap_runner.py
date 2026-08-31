#!/usr/bin/env python3
from __future__ import annotations

from copy import deepcopy

import ctypes
import errno
import hashlib
import json
import os
import secrets
import stat
from pathlib import Path
from typing import Iterable


SCHEMA_VERSION = (
    "memoria-runtime-bootstrap-runner-v0.1"
)

RENAME_NOREPLACE = 1

_DIRECTORY_FLAGS = (
    os.O_RDONLY
    | os.O_DIRECTORY
    | os.O_NOFOLLOW
    | os.O_CLOEXEC
)


def _simple_name(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
        or "\x00" in value
    ):
        raise ValueError(
            "unsafe single path component"
        )

    return value


def _verify_directory_fd(
    fd: int,
    label: str,
) -> None:
    meta = os.fstat(fd)

    if not stat.S_ISDIR(meta.st_mode):
        raise ValueError(
            f"{label} is not a directory"
        )

    if meta.st_uid != 0 or meta.st_gid != 0:
        raise ValueError(
            f"{label} is not root:root"
        )

    if stat.S_IMODE(meta.st_mode) & 0o022:
        raise ValueError(
            f"{label} is group/world writable"
        )


def _verify_regular_metadata(
    meta: os.stat_result,
    *,
    mode: int,
    label: str,
) -> None:
    if not stat.S_ISREG(meta.st_mode):
        raise ValueError(
            f"{label} is not a regular file"
        )

    if meta.st_uid != 0 or meta.st_gid != 0:
        raise ValueError(
            f"{label} is not root:root"
        )

    if stat.S_IMODE(meta.st_mode) != mode:
        raise ValueError(
            f"{label} mode mismatch"
        )


def _open_verified_absolute_directory(
    path: Path,
) -> int:
    path = Path(path)

    if not path.is_absolute():
        raise ValueError(
            "verified directory path must be absolute"
        )

    current_fd = os.open(
        "/",
        _DIRECTORY_FLAGS,
    )

    try:
        _verify_directory_fd(
            current_fd,
            "filesystem root",
        )

        for part in path.parts[1:]:
            _simple_name(part)

            next_fd = os.open(
                part,
                _DIRECTORY_FLAGS,
                dir_fd=current_fd,
            )

            try:
                _verify_directory_fd(
                    next_fd,
                    str(path),
                )
            except Exception:
                os.close(next_fd)
                raise

            os.close(current_fd)
            current_fd = next_fd

        return current_fd

    except Exception:
        os.close(current_fd)
        raise


def _ensure_directory_chain(
    anchor: Path,
    components: Iterable[str],
) -> int:
    """
    Start from one already trusted absolute directory.

    Every existing or newly-created child is reopened with
    O_DIRECTORY|O_NOFOLLOW and verified from its fd.

    Returned fd belongs to the caller.
    """

    current_fd = (
        _open_verified_absolute_directory(
            Path(anchor)
        )
    )

    try:
        for raw_part in components:
            part = _simple_name(raw_part)
            created = False

            try:
                os.mkdir(
                    part,
                    0o755,
                    dir_fd=current_fd,
                )
                created = True

                # Persist the directory entry in the parent.
                os.fsync(current_fd)

            except FileExistsError:
                pass

            next_fd = os.open(
                part,
                _DIRECTORY_FLAGS,
                dir_fd=current_fd,
            )

            try:
                _verify_directory_fd(
                    next_fd,
                    part,
                )

                if created:
                    # mkdir is affected by umask; normalize
                    # only directories created by this call.
                    os.fchown(
                        next_fd,
                        0,
                        0,
                    )
                    os.fchmod(
                        next_fd,
                        0o755,
                    )
                    os.fsync(next_fd)

                    _verify_directory_fd(
                        next_fd,
                        part,
                    )

                    if (
                        stat.S_IMODE(
                            os.fstat(next_fd).st_mode
                        )
                        != 0o755
                    ):
                        raise ValueError(
                            "created directory mode mismatch"
                        )

            except Exception:
                os.close(next_fd)
                raise

            os.close(current_fd)
            current_fd = next_fd

        return current_fd

    except Exception:
        os.close(current_fd)
        raise


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
                "short write"
            )

        offset += written


def _read_hash_at(
    directory_fd: int,
    name: str,
    *,
    mode: int,
) -> str:
    name = _simple_name(name)

    fd = os.open(
        name,
        os.O_RDONLY
        | os.O_NOFOLLOW
        | os.O_CLOEXEC,
        dir_fd=directory_fd,
    )

    try:
        meta = os.fstat(fd)

        _verify_regular_metadata(
            meta,
            mode=mode,
            label=name,
        )

        digest = hashlib.sha256()

        while True:
            chunk = os.read(
                fd,
                64 * 1024,
            )

            if not chunk:
                break

            digest.update(chunk)

        return digest.hexdigest()

    finally:
        os.close(fd)


def _write_verified_regular_file_at(
    directory_fd: int,
    name: str,
    payload: bytes,
    *,
    mode: int,
) -> str:
    """
    Create one new regular file only.

    Existing targets are never replaced.
    """

    name = _simple_name(name)

    if not isinstance(payload, bytes):
        raise TypeError(
            "payload must be bytes"
        )

    expected = hashlib.sha256(
        payload
    ).hexdigest()

    fd = None
    created = False

    try:
        fd = os.open(
            name,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | os.O_NOFOLLOW
            | os.O_CLOEXEC,
            0o600,
            dir_fd=directory_fd,
        )
        created = True

        _write_all(
            fd,
            payload,
        )

        os.fchown(
            fd,
            0,
            0,
        )
        os.fchmod(
            fd,
            mode,
        )
        os.fsync(fd)

        _verify_regular_metadata(
            os.fstat(fd),
            mode=mode,
            label=name,
        )

        os.close(fd)
        fd = None

        actual = _read_hash_at(
            directory_fd,
            name,
            mode=mode,
        )

        if actual != expected:
            raise ValueError(
                f"{name} SHA-256 mismatch"
            )

        os.fsync(directory_fd)

        return actual

    except Exception:
        if fd is not None:
            os.close(fd)

        if created:
            try:
                os.unlink(
                    name,
                    dir_fd=directory_fd,
                )
                os.fsync(directory_fd)
            except FileNotFoundError:
                pass

        raise


_LIBC = ctypes.CDLL(
    None,
    use_errno=True,
)

if not hasattr(_LIBC, "renameat2"):
    raise RuntimeError(
        "libc renameat2 unavailable"
    )

_RENAMEAT2 = _LIBC.renameat2

_RENAMEAT2.argtypes = (
    ctypes.c_int,
    ctypes.c_char_p,
    ctypes.c_int,
    ctypes.c_char_p,
    ctypes.c_uint,
)

_RENAMEAT2.restype = ctypes.c_int


def _rename_noreplace_at(
    parent_fd: int,
    source_name: str,
    target_name: str,
) -> None:
    """
    Atomic same-directory publish.

    Never replaces an existing destination.
    """

    source_name = _simple_name(
        source_name
    )
    target_name = _simple_name(
        target_name
    )

    ctypes.set_errno(0)

    result = _RENAMEAT2(
        parent_fd,
        os.fsencode(source_name),
        parent_fd,
        os.fsencode(target_name),
        RENAME_NOREPLACE,
    )

    if result != 0:
        error_number = ctypes.get_errno()

        if error_number == errno.EEXIST:
            raise FileExistsError(
                error_number,
                os.strerror(error_number),
                target_name,
            )

        raise OSError(
            error_number,
            os.strerror(error_number),
            target_name,
        )

    os.fsync(parent_fd)



def _directory_entries(
    directory_fd: int,
) -> set[str]:
    entries = os.listdir(directory_fd)

    result: set[str] = set()

    for name in entries:
        _simple_name(name)

        if name in result:
            raise ValueError(
                "duplicate directory entry"
            )

        result.add(name)

    return result


def _cleanup_pending_directory_at(
    parent_fd: int,
    pending_name: str,
    allowed_names: set[str],
) -> None:
    """
    Remove only a pending directory created by this runner.

    Unexpected content is never recursively deleted.
    """

    pending_name = _simple_name(
        pending_name
    )

    allowed = {
        _simple_name(name)
        for name in allowed_names
    }

    try:
        pending_fd = os.open(
            pending_name,
            _DIRECTORY_FLAGS,
            dir_fd=parent_fd,
        )
    except FileNotFoundError:
        return

    try:
        _verify_directory_fd(
            pending_fd,
            pending_name,
        )

        entries = _directory_entries(
            pending_fd
        )

        unexpected = entries - allowed

        if unexpected:
            raise ValueError(
                "pending release-state directory "
                "contains unexpected entries"
            )

        for name in sorted(entries):
            meta = os.stat(
                name,
                dir_fd=pending_fd,
                follow_symlinks=False,
            )

            if not stat.S_ISREG(meta.st_mode):
                raise ValueError(
                    "pending release-state entry "
                    "is not regular file"
                )

            os.unlink(
                name,
                dir_fd=pending_fd,
            )

        os.fsync(pending_fd)

    finally:
        os.close(pending_fd)

    os.rmdir(
        pending_name,
        dir_fd=parent_fd,
    )

    os.fsync(parent_fd)


def _publish_release_state_directory_at(
    parent_fd: int,
    final_name: str,
    payloads: dict[str, bytes],
    expected_hashes: dict[str, str],
    *,
    pending_token: str | None = None,
) -> dict[str, object]:
    """
    Build the complete signed release-state directory
    privately, then publish it atomically NO-REPLACE.

    No partial final release-state directory is exposed.
    """

    final_name = _simple_name(
        final_name
    )

    if (
        not isinstance(payloads, dict)
        or not payloads
    ):
        raise ValueError(
            "release-state payloads must be non-empty dict"
        )

    if not isinstance(expected_hashes, dict):
        raise ValueError(
            "release-state hashes must be dict"
        )

    if set(payloads) != set(expected_hashes):
        raise ValueError(
            "release-state payload/hash keyset mismatch"
        )

    names: set[str] = set()

    for name, payload in payloads.items():
        name = _simple_name(name)

        if not isinstance(payload, bytes):
            raise TypeError(
                "release-state payload must be bytes"
            )

        expected = expected_hashes.get(name)

        if (
            not isinstance(expected, str)
            or len(expected) != 64
        ):
            raise ValueError(
                "release-state expected hash invalid"
            )

        try:
            int(expected, 16)
        except ValueError as exc:
            raise ValueError(
                "release-state expected hash invalid"
            ) from exc

        actual = hashlib.sha256(
            payload
        ).hexdigest()

        if actual != expected:
            raise ValueError(
                f"release-state source hash mismatch: {name}"
            )

        names.add(name)

    if pending_token is None:
        pending_token = secrets.token_hex(12)

    pending_token = _simple_name(
        pending_token
    )

    pending_name = (
        f".{final_name}.pending.{pending_token}"
    )

    _simple_name(pending_name)

    pending_fd: int | None = None
    pending_created = False

    try:
        # 0700 while incomplete: only root can inspect it.
        os.mkdir(
            pending_name,
            0o700,
            dir_fd=parent_fd,
        )

        pending_created = True

        os.fsync(parent_fd)

        pending_fd = os.open(
            pending_name,
            _DIRECTORY_FLAGS,
            dir_fd=parent_fd,
        )

        _verify_directory_fd(
            pending_fd,
            pending_name,
        )

        os.fchown(
            pending_fd,
            0,
            0,
        )

        os.fchmod(
            pending_fd,
            0o700,
        )

        os.fsync(pending_fd)

        meta = os.fstat(pending_fd)

        if stat.S_IMODE(meta.st_mode) != 0o700:
            raise ValueError(
                "pending release-state mode mismatch"
            )

        for name in sorted(names):
            _write_verified_regular_file_at(
                pending_fd,
                name,
                payloads[name],
                mode=0o644,
            )

        if _directory_entries(
            pending_fd
        ) != names:
            raise ValueError(
                "pending release-state entry set mismatch"
            )

        verified_hashes: dict[str, str] = {}

        for name in sorted(names):
            actual = _read_hash_at(
                pending_fd,
                name,
                mode=0o644,
            )

            if actual != expected_hashes[name]:
                raise ValueError(
                    f"pending release-state hash drift: {name}"
                )

            verified_hashes[name] = actual

        # Only complete state becomes world-readable.
        os.fchmod(
            pending_fd,
            0o755,
        )

        os.fsync(pending_fd)

        _verify_directory_fd(
            pending_fd,
            pending_name,
        )

        if (
            stat.S_IMODE(
                os.fstat(pending_fd).st_mode
            )
            != 0o755
        ):
            raise ValueError(
                "completed release-state mode mismatch"
            )

        os.close(pending_fd)
        pending_fd = None

        # Atomic same-directory activation.
        _rename_noreplace_at(
            parent_fd,
            pending_name,
            final_name,
        )

        pending_created = False

        # Verify the published final state from its fd.
        final_fd = os.open(
            final_name,
            _DIRECTORY_FLAGS,
            dir_fd=parent_fd,
        )

        try:
            _verify_directory_fd(
                final_fd,
                final_name,
            )

            if (
                stat.S_IMODE(
                    os.fstat(final_fd).st_mode
                )
                != 0o755
            ):
                raise ValueError(
                    "published release-state mode mismatch"
                )

            if _directory_entries(
                final_fd
            ) != names:
                raise ValueError(
                    "published release-state entry set mismatch"
                )

            for name in sorted(names):
                actual = _read_hash_at(
                    final_fd,
                    name,
                    mode=0o644,
                )

                if actual != expected_hashes[name]:
                    raise ValueError(
                        f"published release-state hash drift: {name}"
                    )

        finally:
            os.close(final_fd)

        return {
            "state": "PUBLISHED",
            "target": final_name,
            "hashes": verified_hashes,
        }

    except Exception:
        if pending_fd is not None:
            os.close(pending_fd)
            pending_fd = None

        if pending_created:
            try:
                _cleanup_pending_directory_at(
                    parent_fd,
                    pending_name,
                    names,
                )
            except FileNotFoundError:
                # Rename may already have succeeded while
                # parent fsync subsequently failed.
                pass

        raise



_INTEGRITY_SOURCE = (
    "tools/memoria_release_runtime_integrity.py"
)

_LAUNCHER_SOURCE = (
    "tools/memoria_runtime_launcher.py"
)

_PLAN_SOURCE = (
    "tools/memoria_runtime_bootstrap_plan.py"
)

_BOUND_SOURCE_KEYS = {
    _INTEGRITY_SOURCE,
    _LAUNCHER_SOURCE,
    _PLAN_SOURCE,
}


def _valid_sha256(value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
    ):
        raise ValueError(
            "expected SHA-256 is invalid"
        )

    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(
            "expected SHA-256 is invalid"
        ) from exc

    return value.lower()


def _read_verified_absolute_regular_file(
    path: Path,
    expected_sha256: str,
) -> bytes:
    """
    Reopen one already-plan-bound source through a verified
    parent directory and O_NOFOLLOW, then hash the exact bytes
    before returning them.
    """

    path = Path(path)

    if (
        not path.is_absolute()
        or ".." in path.parts
    ):
        raise ValueError(
            "source path must be safe absolute path"
        )

    expected = _valid_sha256(
        expected_sha256
    )

    parent_fd = (
        _open_verified_absolute_directory(
            path.parent
        )
    )

    fd = None

    try:
        name = _simple_name(path.name)

        fd = os.open(
            name,
            os.O_RDONLY
            | os.O_NOFOLLOW
            | os.O_CLOEXEC,
            dir_fd=parent_fd,
        )

        meta = os.fstat(fd)

        if not stat.S_ISREG(meta.st_mode):
            raise ValueError(
                "bound source is not regular file"
            )

        digest = hashlib.sha256()
        chunks: list[bytes] = []

        while True:
            chunk = os.read(
                fd,
                64 * 1024,
            )

            if not chunk:
                break

            digest.update(chunk)
            chunks.append(chunk)

        actual = digest.hexdigest()

        if actual != expected:
            raise ValueError(
                f"bound source SHA-256 drift: {path}"
            )

        return b"".join(chunks)

    finally:
        if fd is not None:
            os.close(fd)

        os.close(parent_fd)


def _read_bound_bootstrap_sources(
    plan: dict[str, object],
) -> dict[str, dict[str, bytes]]:
    """
    Re-read every byte the Runner will later install.

    Hashes come only from the exact already-approved Plan.
    """

    if not isinstance(plan, dict):
        raise TypeError(
            "bootstrap plan must be dict"
        )

    release = plan.get(
        "active_release"
    )

    if (
        not isinstance(release, str)
        or not release
        or "/" in release
        or "\\" in release
        or "\x00" in release
    ):
        raise ValueError(
            "active release invalid"
        )

    bundle_dir = Path(
        plan.get("bundle_dir", "")
    )

    project_root = Path(
        plan.get("project_root", "")
    )

    if (
        not bundle_dir.is_absolute()
        or ".." in bundle_dir.parts
        or not project_root.is_absolute()
        or ".." in project_root.parts
    ):
        raise ValueError(
            "bound source roots invalid"
        )

    release_hashes = plan.get(
        "release_state_hashes"
    )

    source_hashes = plan.get(
        "source_hashes"
    )

    if not isinstance(release_hashes, dict):
        raise ValueError(
            "release_state_hashes must be dict"
        )

    if not isinstance(source_hashes, dict):
        raise ValueError(
            "source_hashes must be dict"
        )

    manifest_name = (
        f"MEMORIA-{release}.payload.sha256"
    )

    release_names = {
        "SHA256SUMS",
        "SHA256SUMS.sig",
        manifest_name,
    }

    if set(release_hashes) != release_names:
        raise ValueError(
            "release-state hash keyset mismatch"
        )

    if set(source_hashes) != _BOUND_SOURCE_KEYS:
        raise ValueError(
            "bound source hash keyset mismatch"
        )

    release_payloads: dict[str, bytes] = {}

    for name in sorted(release_names):
        release_payloads[name] = (
            _read_verified_absolute_regular_file(
                bundle_dir / name,
                _valid_sha256(
                    release_hashes[name]
                ),
            )
        )

    runtime_payloads: dict[str, bytes] = {}

    for relative in (
        _INTEGRITY_SOURCE,
        _LAUNCHER_SOURCE,
    ):
        runtime_payloads[relative] = (
            _read_verified_absolute_regular_file(
                project_root / relative,
                _valid_sha256(
                    source_hashes[relative]
                ),
            )
        )

    _read_verified_absolute_regular_file(
        project_root / _PLAN_SOURCE,
        _valid_sha256(
            source_hashes[_PLAN_SOURCE]
        ),
    )

    return {
        "release_state": release_payloads,
        "runtime": runtime_payloads,
    }


def _verify_existing_release_state(
    target: Path,
    expected_hashes: dict[str, str],
) -> dict[str, str]:
    target = Path(target)

    if not target.is_absolute():
        raise ValueError(
            "release-state target must be absolute"
        )

    if not isinstance(expected_hashes, dict):
        raise ValueError(
            "release-state expected hashes must be dict"
        )

    directory_fd = (
        _open_verified_absolute_directory(
            target
        )
    )

    try:
        meta = os.fstat(directory_fd)

        if stat.S_IMODE(meta.st_mode) != 0o755:
            raise ValueError(
                "release-state directory mode mismatch"
            )

        verified: dict[str, str] = {}

        for name in sorted(expected_hashes):
            expected = _valid_sha256(
                expected_hashes[name]
            )

            actual = _read_hash_at(
                directory_fd,
                _simple_name(name),
                mode=0o644,
            )

            if actual != expected:
                raise ValueError(
                    f"release-state target drift: {name}"
                )

            verified[name] = actual

        return verified

    finally:
        os.close(directory_fd)


def _verify_existing_regular_target(
    target: Path,
    expected_sha256: str,
    *,
    mode: int,
) -> str:
    target = Path(target)

    if not target.is_absolute():
        raise ValueError(
            "installed target must be absolute"
        )

    parent_fd = (
        _open_verified_absolute_directory(
            target.parent
        )
    )

    try:
        actual = _read_hash_at(
            parent_fd,
            target.name,
            mode=mode,
        )

        expected = _valid_sha256(
            expected_sha256
        )

        if actual != expected:
            raise ValueError(
                f"installed target SHA-256 drift: {target}"
            )

        return actual

    finally:
        os.close(parent_fd)


def _verify_bound_prestaged_targets(
    plan: dict[str, object],
) -> dict[str, str]:
    """
    Validate every bound ALREADY STAGED target again.

    ABSENT is a no-op here.
    PARTIAL / DRIFT / UNSAFE are never repaired.
    """

    if not isinstance(plan, dict):
        raise TypeError(
            "bootstrap plan must be dict"
        )

    allowed = {
        "ABSENT",
        "ALREADY STAGED",
    }

    states = {
        "release_state":
            plan.get("release_state_target_state"),
        "bootstrap":
            plan.get("bootstrap_target_state"),
        "launcher":
            plan.get("launcher_target_state"),
    }

    for label, state in states.items():
        if state not in allowed:
            raise ValueError(
                f"{label} target state not fresh-safe: {state}"
            )

    if plan.get(
        "identity_target_state"
    ) != "ABSENT":
        raise ValueError(
            "installed identity must remain ABSENT"
        )

    source_hashes = plan.get(
        "source_hashes"
    )

    release_hashes = plan.get(
        "release_state_hashes"
    )

    if not isinstance(source_hashes, dict):
        raise ValueError(
            "source_hashes must be dict"
        )

    if not isinstance(release_hashes, dict):
        raise ValueError(
            "release_state_hashes must be dict"
        )

    result = {
        "release_state": states["release_state"],
        "bootstrap": states["bootstrap"],
        "launcher": states["launcher"],
    }

    if states["release_state"] == "ALREADY STAGED":
        _verify_existing_release_state(
            Path(
                str(
                    plan.get(
                        "release_state_target"
                    )
                )
            ),
            release_hashes,
        )

    if states["bootstrap"] == "ALREADY STAGED":
        _verify_existing_regular_target(
            Path(
                str(
                    plan.get(
                        "bootstrap_target"
                    )
                )
            ),
            _valid_sha256(
                source_hashes[
                    _INTEGRITY_SOURCE
                ]
            ),
            mode=0o644,
        )

    if states["launcher"] == "ALREADY STAGED":
        _verify_existing_regular_target(
            Path(
                str(
                    plan.get(
                        "launcher_target"
                    )
                )
            ),
            _valid_sha256(
                source_hashes[
                    _LAUNCHER_SOURCE
                ]
            ),
            mode=0o755,
        )

    return result




_EXECUTION_TICKET_SCHEMA = (
    "memoria-runtime-bootstrap-execution-ticket-v0.1"
)

_EXECUTION_HANDOFF_KEYS = {
    "approval_id",
    "plan_sha256",
    "plan",
    "payloads",
    "target_states",
}


class RuntimeBootstrapExecutionHandoffStore:
    """
    Process-local one-shot execution capability registry.

    The public ticket contains no payload bytes.
    Only a successfully claimed registered ticket releases
    the internally stored execution handoff.

    No filesystem persistence exists here.
    """

    def __init__(
        self,
        ticket_factory=None,
    ):
        if ticket_factory is None:
            ticket_factory = (
                lambda: secrets.token_urlsafe(24)
            )

        self._ticket_factory = ticket_factory
        self._records = {}

    def _register_after_consume(
        self,
        handoff,
    ):
        if not isinstance(handoff, dict):
            raise TypeError(
                "execution handoff must be dict"
            )

        if set(handoff) != _EXECUTION_HANDOFF_KEYS:
            raise ValueError(
                "execution handoff keys are not exact"
            )

        approval_id = handoff.get(
            "approval_id"
        )

        if (
            not isinstance(approval_id, str)
            or not approval_id
        ):
            raise ValueError(
                "execution handoff approval_id invalid"
            )

        plan_sha256 = _valid_sha256(
            handoff.get("plan_sha256")
        )

        plan = handoff.get("plan")

        if (
            not isinstance(plan, dict)
            or plan.get("plan_sha256")
            != plan_sha256
        ):
            raise ValueError(
                "execution handoff plan binding invalid"
            )

        if not isinstance(
            handoff.get("payloads"),
            dict,
        ):
            raise ValueError(
                "execution handoff payloads invalid"
            )

        if not isinstance(
            handoff.get("target_states"),
            dict,
        ):
            raise ValueError(
                "execution handoff target states invalid"
            )

        ticket_id = self._ticket_factory()

        if (
            not isinstance(ticket_id, str)
            or not ticket_id
        ):
            raise ValueError(
                "execution ticket factory returned invalid id"
            )

        if ticket_id in self._records:
            raise ValueError(
                "duplicate execution ticket"
            )

        ticket = {
            "schema_version":
                _EXECUTION_TICKET_SCHEMA,
            "ticket_id":
                ticket_id,
            "approval_id":
                approval_id,
            "plan_sha256":
                plan_sha256,
            "one_shot":
                True,
            "claimed":
                False,
            "persistence":
                "MEMORY ONLY",
        }

        self._records[ticket_id] = {
            "ticket":
                deepcopy(ticket),
            "handoff":
                deepcopy(handoff),
            "claimed":
                False,
        }

        return deepcopy(ticket)

    def claim_for_execution(
        self,
        ticket,
    ):
        blocked = {
            "schema_version":
                _EXECUTION_TICKET_SCHEMA,
            "ticket_status":
                "BLOCKED",
            "ticket_id":
                None,
            "approval_id":
                None,
            "plan_sha256":
                None,
            "one_shot":
                True,
            "claimed":
                False,
            "persistence":
                "MEMORY ONLY",
            "reason":
                None,
        }

        if not isinstance(ticket, dict):
            blocked["reason"] = (
                "Execution ticket must be dict."
            )
            return False, blocked, None

        if ticket.get(
            "schema_version"
        ) != _EXECUTION_TICKET_SCHEMA:
            blocked["reason"] = (
                "Execution ticket schema mismatch."
            )
            return False, blocked, None

        ticket_id = ticket.get(
            "ticket_id"
        )

        if (
            not isinstance(ticket_id, str)
            or not ticket_id
        ):
            blocked["reason"] = (
                "Missing execution ticket id."
            )
            return False, blocked, None

        blocked["ticket_id"] = ticket_id

        record = self._records.get(
            ticket_id
        )

        if record is None:
            blocked["reason"] = (
                "Unknown execution ticket."
            )
            return False, blocked, None

        stored_ticket = record["ticket"]

        blocked["approval_id"] = (
            stored_ticket.get("approval_id")
        )

        blocked["plan_sha256"] = (
            stored_ticket.get("plan_sha256")
        )

        if record.get("claimed") is True:
            blocked["claimed"] = True
            blocked["reason"] = (
                "Execution ticket already claimed."
            )
            return False, blocked, None

        # Modified presented copies do not destroy the
        # legitimate registered ticket.
        if ticket != stored_ticket:
            blocked["reason"] = (
                "Presented execution ticket was modified."
            )
            return False, blocked, None

        if (
            stored_ticket.get("one_shot")
            is not True
        ):
            blocked["reason"] = (
                "Execution ticket is not one-shot."
            )
            return False, blocked, None

        if (
            stored_ticket.get("persistence")
            != "MEMORY ONLY"
        ):
            blocked["reason"] = (
                "Unexpected execution ticket persistence."
            )
            return False, blocked, None

        if stored_ticket.get(
            "claimed"
        ) is not False:
            blocked["reason"] = (
                "Unexpected execution ticket state."
            )
            return False, blocked, None

        handoff = record.get(
            "handoff"
        )

        if (
            not isinstance(handoff, dict)
            or set(handoff)
            != _EXECUTION_HANDOFF_KEYS
            or handoff.get("approval_id")
            != stored_ticket.get("approval_id")
            or handoff.get("plan_sha256")
            != stored_ticket.get("plan_sha256")
        ):
            blocked["reason"] = (
                "Registered execution handoff drift."
            )
            return False, blocked, None

        # Claim BEFORE the future write layer receives
        # the internal handoff. A failed execution attempt
        # must never make this ticket reusable.
        record["claimed"] = True

        claimed = deepcopy(
            stored_ticket
        )

        claimed["claimed"] = True
        claimed["ticket_status"] = (
            "CLAIMED FOR ONE EXECUTION ATTEMPT"
        )
        claimed["reason"] = (
            "Execution ticket claimed. "
            "No filesystem execution exists in "
            "this handoff layer."
        )

        return (
            True,
            claimed,
            deepcopy(handoff),
        )


def _prepare_runtime_bootstrap_handoff(
    store,
    authorization,
    bundle_context,
    *,
    execution_store,
    plan_builder,
    plan_identity_verifier,
    plan_approvable,
):
    """
    Consume exactly one authorization and return only an
    in-memory execution handoff.

    This helper performs no filesystem write.
    """

    result = {
        "runner_status": "BLOCKED",
        "authorization_consumed": False,
        "execution_authorized": False,
        "execution_performed": False,
        "plan_sha256": None,
        "approval_id": None,
        "reason": None,
    }

    # -------------------------------------------------
    # PRE-CONSUME
    # -------------------------------------------------

    try:
        current_plan = plan_builder(
            bundle_context
        )
    except Exception as exc:
        result["reason"] = (
            "Pre-consume plan build failed: "
            f"{type(exc).__name__}."
        )
        return 5, result, None

    result["plan_sha256"] = (
        current_plan.get("plan_sha256")
        if isinstance(current_plan, dict)
        else None
    )

    if (
        not isinstance(current_plan, dict)
        or plan_identity_verifier(
            current_plan
        ) is not True
        or plan_approvable(
            current_plan
        ) is not True
    ):
        result["reason"] = (
            "Pre-consume plan is not valid and approvable."
        )
        return 5, result, None

    try:
        pre_payloads = (
            _read_bound_bootstrap_sources(
                current_plan
            )
        )

        pre_states = (
            _verify_bound_prestaged_targets(
                current_plan
            )
        )
    except Exception as exc:
        result["reason"] = (
            "Pre-consume bound verification failed: "
            f"{type(exc).__name__}."
        )
        return 5, result, None

    # Keep variables deliberately used: this proves the
    # complete pre-consume verification occurred.
    del pre_payloads
    del pre_states

    allowed, consumed = (
        store.verify_and_consume(
            authorization,
            current_plan,
        )
    )

    result["authorization_consumed"] = (
        consumed.get("consumed") is True
    )

    result["approval_id"] = consumed.get(
        "approval_id"
    )

    result["plan_sha256"] = (
        current_plan.get("plan_sha256")
    )

    if allowed is not True:
        result["reason"] = consumed.get(
            "reason",
            "One-shot authorization rejected.",
        )
        return 5, result, None

    if (
        consumed.get("consumed") is not True
        or consumed.get(
            "execution_performed"
        ) is not False
        or consumed.get(
            "plan_sha256"
        ) != current_plan.get(
            "plan_sha256"
        )
    ):
        result["runner_status"] = (
            "BLOCKED AFTER CONSUME"
        )
        result["reason"] = (
            "Consumed authorization contract invalid. "
            "Authorization remains consumed."
        )
        return 6, result, None

    result["execution_authorized"] = True

    # -------------------------------------------------
    # POST-CONSUME FINAL READ-ONLY REVALIDATION
    # -------------------------------------------------

    try:
        post_plan = plan_builder(
            bundle_context
        )
    except Exception as exc:
        result["runner_status"] = (
            "BLOCKED AFTER CONSUME"
        )
        result["reason"] = (
            "Post-consume plan build failed: "
            f"{type(exc).__name__}. "
            "Authorization remains consumed."
        )
        return 6, result, None

    if (
        not isinstance(post_plan, dict)
        or plan_identity_verifier(
            post_plan
        ) is not True
        or plan_approvable(
            post_plan
        ) is not True
        or post_plan.get(
            "plan_sha256"
        ) != consumed.get(
            "plan_sha256"
        )
    ):
        result["runner_status"] = (
            "BLOCKED AFTER CONSUME"
        )
        result["reason"] = (
            "Bootstrap plan drifted after authorization "
            "consumption. Authorization remains consumed."
        )
        return 6, result, None

    try:
        post_payloads = (
            _read_bound_bootstrap_sources(
                post_plan
            )
        )

        post_states = (
            _verify_bound_prestaged_targets(
                post_plan
            )
        )
    except Exception as exc:
        result["runner_status"] = (
            "BLOCKED AFTER CONSUME"
        )
        result["reason"] = (
            "Post-consume bound verification failed: "
            f"{type(exc).__name__}. "
            "Authorization remains consumed."
        )
        return 6, result, None

    handoff = {
        "approval_id":
            consumed.get("approval_id"),
        "plan_sha256":
            post_plan["plan_sha256"],
        "plan":
            post_plan,
        "payloads":
            post_payloads,
        "target_states":
            post_states,
    }

    try:
        ticket = (
            execution_store._register_after_consume(
                handoff
            )
        )
    except Exception as exc:
        result["runner_status"] = (
            "BLOCKED AFTER CONSUME"
        )
        result["reason"] = (
            "Execution-ticket registration failed: "
            f"{type(exc).__name__}. "
            "Authorization remains consumed."
        )
        return 6, result, None

    result["runner_status"] = (
        "READY FOR EXECUTION"
    )

    result["reason"] = (
        "Authorization consumed, final read-only "
        "bootstrap state revalidated, and one-shot "
        "execution ticket registered."
    )

    return 0, result, ticket



def _publish_verified_regular_file_at(
    parent_fd: int,
    final_name: str,
    payload: bytes,
    expected_sha256: str,
    *,
    mode: int,
    pending_token: str | None = None,
) -> dict[str, object]:
    """
    Publish one complete regular file atomically.

    The final name is never exposed with partial contents.
    Existing final targets are never replaced.
    """

    final_name = _simple_name(
        final_name
    )

    if not isinstance(payload, bytes):
        raise TypeError(
            "regular-file payload must be bytes"
        )

    expected = _valid_sha256(
        expected_sha256
    )

    actual_source = hashlib.sha256(
        payload
    ).hexdigest()

    if actual_source != expected:
        raise ValueError(
            "regular-file source SHA-256 mismatch"
        )

    if pending_token is None:
        pending_token = secrets.token_hex(12)

    pending_token = _simple_name(
        pending_token
    )

    pending_name = (
        f".{final_name}.pending.{pending_token}"
    )

    _simple_name(
        pending_name
    )

    pending_created = False

    try:
        _write_verified_regular_file_at(
            parent_fd,
            pending_name,
            payload,
            mode=mode,
        )

        pending_created = True

        pending_sha = _read_hash_at(
            parent_fd,
            pending_name,
            mode=mode,
        )

        if pending_sha != expected:
            raise ValueError(
                "pending regular-file SHA-256 mismatch"
            )

        _rename_noreplace_at(
            parent_fd,
            pending_name,
            final_name,
        )

        # After successful atomic rename the pending name
        # no longer exists. Never roll back the published
        # final file automatically.
        pending_created = False

        final_sha = _read_hash_at(
            parent_fd,
            final_name,
            mode=mode,
        )

        if final_sha != expected:
            raise ValueError(
                "published regular-file SHA-256 mismatch"
            )

        return {
            "state": "PUBLISHED",
            "target": final_name,
            "sha256": final_sha,
            "mode": mode,
        }

    except Exception:
        if pending_created:
            try:
                os.unlink(
                    pending_name,
                    dir_fd=parent_fd,
                )
                os.fsync(parent_fd)

            except FileNotFoundError:
                # Rename may already have completed.
                # Never remove the final published target.
                pass

        raise



def _assert_target_still_absent(
    target: Path,
    label: str,
) -> None:
    """
    Verify one absolute target is still absent without
    following symlink components.

    If an intermediate parent is absent, the final target
    is necessarily absent as well.
    """

    target = Path(target)

    if (
        not target.is_absolute()
        or ".." in target.parts
    ):
        raise ValueError(
            f"{label} target path invalid"
        )

    current_fd = os.open(
        "/",
        _DIRECTORY_FLAGS,
    )

    try:
        _verify_directory_fd(
            current_fd,
            "filesystem root",
        )

        for part in target.parent.parts[1:]:
            part = _simple_name(part)

            try:
                next_fd = os.open(
                    part,
                    _DIRECTORY_FLAGS,
                    dir_fd=current_fd,
                )
            except FileNotFoundError:
                # Missing parent proves final target absent.
                return

            try:
                _verify_directory_fd(
                    next_fd,
                    part,
                )
            except Exception:
                os.close(next_fd)
                raise

            os.close(current_fd)
            current_fd = next_fd

        name = _simple_name(
            target.name
        )

        try:
            os.stat(
                name,
                dir_fd=current_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            return

        raise FileExistsError(
            f"{label} target appeared after authorization"
        )

    finally:
        os.close(current_fd)


def _claim_and_revalidate_execution_ticket(
    execution_store,
    ticket,
):
    """
    Claim the one-shot execution ticket BEFORE any write,
    then perform one final read-only race/drift check.

    Failure after claim never makes the ticket reusable.
    """

    result = {
        "runner_status":
            "BLOCKED",
        "execution_ticket_claimed":
            False,
        "execution_performed":
            False,
        "approval_id":
            None,
        "plan_sha256":
            None,
        "reason":
            None,
    }

    allowed, claimed, handoff = (
        execution_store.claim_for_execution(
            ticket
        )
    )

    result["execution_ticket_claimed"] = (
        claimed.get("claimed") is True
    )

    result["approval_id"] = claimed.get(
        "approval_id"
    )

    result["plan_sha256"] = claimed.get(
        "plan_sha256"
    )

    if allowed is not True:
        result["reason"] = claimed.get(
            "reason",
            "Execution ticket rejected.",
        )
        return 5, result, None

    if (
        handoff is None
        or not isinstance(handoff, dict)
        or set(handoff)
        != _EXECUTION_HANDOFF_KEYS
    ):
        result["runner_status"] = (
            "BLOCKED AFTER CLAIM"
        )
        result["reason"] = (
            "Claimed execution handoff invalid. "
            "Ticket remains spent."
        )
        return 6, result, None

    plan = handoff.get(
        "plan"
    )

    if (
        not isinstance(plan, dict)
        or handoff.get("plan_sha256")
        != claimed.get("plan_sha256")
        or plan.get("plan_sha256")
        != claimed.get("plan_sha256")
    ):
        result["runner_status"] = (
            "BLOCKED AFTER CLAIM"
        )
        result["reason"] = (
            "Claimed execution plan binding invalid. "
            "Ticket remains spent."
        )
        return 6, result, None

    # Re-read exact signed sources AFTER claim.
    try:
        current_payloads = (
            _read_bound_bootstrap_sources(
                plan
            )
        )
    except Exception as exc:
        result["runner_status"] = (
            "BLOCKED AFTER CLAIM"
        )
        result["reason"] = (
            "Post-claim source verification failed: "
            f"{type(exc).__name__}. "
            "Ticket remains spent."
        )
        return 6, result, None

    if current_payloads != handoff.get(
        "payloads"
    ):
        result["runner_status"] = (
            "BLOCKED AFTER CLAIM"
        )
        result["reason"] = (
            "Post-claim source bytes no longer match "
            "registered handoff. Ticket remains spent."
        )
        return 6, result, None

    states = handoff.get(
        "target_states"
    )

    if set(states or {}) != {
        "release_state",
        "bootstrap",
        "launcher",
    }:
        result["runner_status"] = (
            "BLOCKED AFTER CLAIM"
        )
        result["reason"] = (
            "Registered target-state set invalid. "
            "Ticket remains spent."
        )
        return 6, result, None

    source_hashes = plan.get(
        "source_hashes"
    )

    release_hashes = plan.get(
        "release_state_hashes"
    )

    if (
        not isinstance(source_hashes, dict)
        or not isinstance(release_hashes, dict)
    ):
        result["runner_status"] = (
            "BLOCKED AFTER CLAIM"
        )
        result["reason"] = (
            "Bound hash maps invalid. "
            "Ticket remains spent."
        )
        return 6, result, None

    try:
        # ---------------------------------------------
        # Release state
        # ---------------------------------------------
        if states["release_state"] == "ALREADY STAGED":
            _verify_existing_release_state(
                Path(
                    plan["release_state_target"]
                ),
                release_hashes,
            )

        elif states["release_state"] == "ABSENT":
            _assert_target_still_absent(
                Path(
                    plan["release_state_target"]
                ),
                "release-state",
            )

        else:
            raise ValueError(
                "release-state handoff state invalid"
            )

        # ---------------------------------------------
        # Bootstrap verifier
        # ---------------------------------------------
        if states["bootstrap"] == "ALREADY STAGED":
            _verify_existing_regular_target(
                Path(
                    plan["bootstrap_target"]
                ),
                _valid_sha256(
                    source_hashes[
                        _INTEGRITY_SOURCE
                    ]
                ),
                mode=0o644,
            )

        elif states["bootstrap"] == "ABSENT":
            _assert_target_still_absent(
                Path(
                    plan["bootstrap_target"]
                ),
                "bootstrap verifier",
            )

        else:
            raise ValueError(
                "bootstrap handoff state invalid"
            )

        # ---------------------------------------------
        # Launcher
        # ---------------------------------------------
        if states["launcher"] == "ALREADY STAGED":
            _verify_existing_regular_target(
                Path(
                    plan["launcher_target"]
                ),
                _valid_sha256(
                    source_hashes[
                        _LAUNCHER_SOURCE
                    ]
                ),
                mode=0o755,
            )

        elif states["launcher"] == "ABSENT":
            _assert_target_still_absent(
                Path(
                    plan["launcher_target"]
                ),
                "launcher",
            )

        else:
            raise ValueError(
                "launcher handoff state invalid"
            )

        # Installed Identity must STILL be absent.
        _assert_target_still_absent(
            Path(
                plan["identity_target"]
            ),
            "installed identity",
        )

    except Exception as exc:
        result["runner_status"] = (
            "BLOCKED AFTER CLAIM"
        )
        result["reason"] = (
            "Post-claim target revalidation failed: "
            f"{type(exc).__name__}. "
            "Ticket remains spent."
        )
        return 6, result, None

    execution_handoff = deepcopy(
        handoff
    )

    # Use the freshly post-claim verified bytes.
    execution_handoff["payloads"] = (
        current_payloads
    )

    result["runner_status"] = (
        "READY FOR FIRST WRITE"
    )

    result["reason"] = (
        "Execution ticket claimed and all bound sources, "
        "target states, and Installed Identity were "
        "revalidated immediately before execution."
    )

    return (
        0,
        result,
        execution_handoff,
    )



def _ensure_target_parent_directory(
    target: Path,
) -> int:
    target = Path(target)

    if (
        not target.is_absolute()
        or ".." in target.parts
    ):
        raise ValueError(
            "execution target must be safe absolute path"
        )

    return _ensure_directory_chain(
        Path("/"),
        target.parent.parts[1:],
    )


def _execute_runtime_bootstrap_write_layer_with_committer(
    execution_store,
    ticket,
    *,
    identity_committer,
):
    """
    Internal testable core for one authorized fresh-bootstrap activation attempt:

    1. release state
    2. runtime-integrity verifier
    3. launcher
    4. pre-activation Runtime Integrity verification
    5. Installed Identity commit as the final activation anchor
    6. post-activation Runtime Integrity verification

    The execution ticket is one-shot. No automatic rollback
    or retry is performed after activation begins.
    """

    result = {
        "runner_status":
            "BLOCKED",
        "execution_ticket_claimed":
            False,
        "execution_performed":
            False,
        "filesystem_write_attempted":
            False,
        "approval_id":
            None,
        "plan_sha256":
            None,
        "completed_targets":
            [],
        "reason":
            None,
    }

    status, guard, handoff = (
        _claim_and_revalidate_execution_ticket(
            execution_store,
            ticket,
        )
    )

    result["execution_ticket_claimed"] = (
        guard.get(
            "execution_ticket_claimed"
        ) is True
    )

    result["approval_id"] = guard.get(
        "approval_id"
    )

    result["plan_sha256"] = guard.get(
        "plan_sha256"
    )

    if status != 0 or handoff is None:
        result["runner_status"] = guard.get(
            "runner_status",
            "BLOCKED",
        )
        result["reason"] = guard.get(
            "reason",
            "Execution ticket rejected.",
        )
        return status, result

    plan = handoff["plan"]
    payloads = handoff["payloads"]
    states = handoff["target_states"]

    release_target = Path(
        plan["release_state_target"]
    )

    bootstrap_target = Path(
        plan["bootstrap_target"]
    )

    launcher_target = Path(
        plan["launcher_target"]
    )

    identity_target = Path(
        plan["identity_target"]
    )

    release_hashes = plan[
        "release_state_hashes"
    ]

    source_hashes = plan[
        "source_hashes"
    ]

    try:
        # =================================================
        # 1. RELEASE STATE
        # =================================================

        _assert_target_still_absent(
            identity_target,
            "installed identity",
        )

        if states["release_state"] == "ALREADY STAGED":
            _verify_existing_release_state(
                release_target,
                release_hashes,
            )

            result["completed_targets"].append(
                "release_state:reused"
            )

        elif states["release_state"] == "ABSENT":
            result["filesystem_write_attempted"] = True
            result["execution_performed"] = True

            parent_fd = (
                _ensure_target_parent_directory(
                    release_target
                )
            )

            try:
                _publish_release_state_directory_at(
                    parent_fd,
                    release_target.name,
                    payloads["release_state"],
                    release_hashes,
                )
            finally:
                os.close(parent_fd)

            result["completed_targets"].append(
                "release_state:published"
            )

        else:
            raise ValueError(
                "release-state execution state invalid"
            )

        _verify_existing_release_state(
            release_target,
            release_hashes,
        )

        # =================================================
        # 2. RUNTIME INTEGRITY VERIFIER
        # =================================================

        _assert_target_still_absent(
            identity_target,
            "installed identity",
        )

        integrity_sha = _valid_sha256(
            source_hashes[
                _INTEGRITY_SOURCE
            ]
        )

        if states["bootstrap"] == "ALREADY STAGED":
            _verify_existing_regular_target(
                bootstrap_target,
                integrity_sha,
                mode=0o644,
            )

            result["completed_targets"].append(
                "bootstrap:reused"
            )

        elif states["bootstrap"] == "ABSENT":
            result["filesystem_write_attempted"] = True
            result["execution_performed"] = True

            parent_fd = (
                _ensure_target_parent_directory(
                    bootstrap_target
                )
            )

            try:
                _publish_verified_regular_file_at(
                    parent_fd,
                    bootstrap_target.name,
                    payloads["runtime"][
                        _INTEGRITY_SOURCE
                    ],
                    integrity_sha,
                    mode=0o644,
                )
            finally:
                os.close(parent_fd)

            result["completed_targets"].append(
                "bootstrap:published"
            )

        else:
            raise ValueError(
                "bootstrap execution state invalid"
            )

        _verify_existing_regular_target(
            bootstrap_target,
            integrity_sha,
            mode=0o644,
        )

        # =================================================
        # 3. LAUNCHER
        # =================================================

        _assert_target_still_absent(
            identity_target,
            "installed identity",
        )

        launcher_sha = _valid_sha256(
            source_hashes[
                _LAUNCHER_SOURCE
            ]
        )

        if states["launcher"] == "ALREADY STAGED":
            _verify_existing_regular_target(
                launcher_target,
                launcher_sha,
                mode=0o755,
            )

            result["completed_targets"].append(
                "launcher:reused"
            )

        elif states["launcher"] == "ABSENT":
            result["filesystem_write_attempted"] = True
            result["execution_performed"] = True

            parent_fd = (
                _ensure_target_parent_directory(
                    launcher_target
                )
            )

            try:
                _publish_verified_regular_file_at(
                    parent_fd,
                    launcher_target.name,
                    payloads["runtime"][
                        _LAUNCHER_SOURCE
                    ],
                    launcher_sha,
                    mode=0o755,
                )
            finally:
                os.close(parent_fd)

            result["completed_targets"].append(
                "launcher:published"
            )

        else:
            raise ValueError(
                "launcher execution state invalid"
            )

        _verify_existing_regular_target(
            launcher_target,
            launcher_sha,
            mode=0o755,
        )

        # =================================================
        # 4. FINAL INERT-STAGING VERIFICATION
        # =================================================

        _assert_target_still_absent(
            identity_target,
            "installed identity",
        )

        _verify_existing_release_state(
            release_target,
            release_hashes,
        )

        _verify_existing_regular_target(
            bootstrap_target,
            integrity_sha,
            mode=0o644,
        )

        _verify_existing_regular_target(
            launcher_target,
            launcher_sha,
            mode=0o755,
        )

        pre_status, pre_result = (
            _verify_pre_activation_runtime_integrity(
                handoff
            )
        )

        result["pre_activation_result"] = (
            pre_result
        )

        result["pre_activation_verified"] = (
            pre_status == 0
            and pre_result.get(
                "verified"
            ) is True
        )

        if result[
            "pre_activation_verified"
        ] is not True:
            result["runner_status"] = (
                "PRE-ACTIVATION VERIFY FAILED"
            )

            result["reason"] = (
                pre_result.get(
                    "reason",
                    "Pre-activation integrity failed.",
                )
                + " Execution ticket remains spent. "
                "Already-safe staged artifacts are retained. "
                "No automatic rollback or retry."
            )

            return 12, result

        # =================================================
        # 5. IDENTITY COMMIT = FINAL ACTIVATION ANCHOR
        # =================================================

        if not callable(identity_committer):
            raise TypeError(
                "Identity committer must be callable"
            )

        activation_status, activation_result = (
            identity_committer(
                handoff
            )
        )

        if not isinstance(
            activation_result,
            dict,
        ):
            raise ValueError(
                "Identity activation result invalid"
            )

        result["activation_result"] = (
            activation_result
        )

        result["identity_published"] = (
            activation_result.get(
                "identity_published"
            ) is True
        )

        result["post_activation_verified"] = (
            activation_result.get(
                "post_activation_verified"
            ) is True
        )

        if result["identity_published"]:
            result["filesystem_write_attempted"] = True
            result["execution_performed"] = True

        if (
            activation_status != 0
            or result[
                "post_activation_verified"
            ] is not True
        ):
            result["runner_status"] = (
                activation_result.get(
                    "activation_status",
                    "ACTIVATION FAILED",
                )
            )

            result["reason"] = (
                activation_result.get(
                    "reason",
                    "Runtime activation failed.",
                )
                + " Execution ticket remains spent. "
                "No automatic rollback or retry."
            )

            if (
                isinstance(
                    activation_status,
                    int,
                )
                and activation_status != 0
            ):
                return activation_status, result

            return 14, result

        result["runner_status"] = (
            "ACTIVATED AND VERIFIED"
        )

        result["reason"] = (
            "Runtime staging and pre-activation integrity "
            "completed. Installed Identity was committed "
            "last and post-activation Runtime Integrity "
            "verification succeeded."
        )

        return 0, result

    except FileExistsError as exc:
        result["runner_status"] = (
            "BLOCKED AFTER CLAIM"
        )

        result["reason"] = (
            "A final target appeared during execution. "
            "Existing target was not adopted or overwritten. "
            "Execution ticket remains spent. "
            f"{type(exc).__name__}."
        )

        return 7, result

    except Exception as exc:
        result["runner_status"] = (
            "EXECUTION ERROR"
        )

        result["reason"] = (
            "Runtime bootstrap staging failed: "
            f"{type(exc).__name__}. "
            "Execution ticket remains spent. "
            "Already-safe staged artifacts are retained. "
            "No automatic rollback or retry."
        )

        return 11, result



_PRE_ACTIVATION_EXPECTED_FINGERPRINT = (
    "2A43DDB1EB6CAE0E011D8C688F3BBFD776DF59A3"
)

_PRE_ACTIVATION_TRUST_ANCHOR = Path(
    "/usr/share/keyrings/memoria-release.gpg"
)


def _execute_runtime_bootstrap_write_layer(
    execution_store,
    ticket,
):
    """
    Production execution surface.

    Always binds the canonical Identity commit and
    post-activation verification path. Callers cannot
    inject an alternate Identity committer.
    """

    return (
        _execute_runtime_bootstrap_write_layer_with_committer(
            execution_store,
            ticket,
            identity_committer=(
                _commit_runtime_identity_and_postverify
            ),
        )
    )


def _verify_pre_activation_runtime_integrity(
    handoff,
):
    """
    Verify the complete signed release payload with the exact
    already-staged Runtime Integrity verifier.

    This is an internal post-write / pre-Identity check.
    It is NOT an authorization boundary and performs no writes.
    """

    result = {
        "pre_activation_status":
            "BLOCKED",
        "verified":
            False,
        "fingerprint":
            None,
        "manifest_sha256":
            None,
        "entries":
            None,
        "match":
            None,
        "drift":
            None,
        "missing":
            None,
        "unsafe":
            None,
        "reason":
            None,
    }

    try:
        if (
            not isinstance(handoff, dict)
            or set(handoff)
            != _EXECUTION_HANDOFF_KEYS
        ):
            raise ValueError(
                "execution handoff invalid"
            )

        plan = handoff.get(
            "plan"
        )

        if not isinstance(plan, dict):
            raise ValueError(
                "execution plan invalid"
            )

        release = plan.get(
            "active_release"
        )

        if (
            not isinstance(release, str)
            or not release
            or "/" in release
            or "\\" in release
            or "\x00" in release
        ):
            raise ValueError(
                "active release invalid"
            )

        signer = plan.get(
            "signer_fingerprint"
        )

        if signer != (
            _PRE_ACTIVATION_EXPECTED_FINGERPRINT
        ):
            raise ValueError(
                "bound signer fingerprint mismatch"
            )

        project_root = Path(
            plan["project_root"]
        )

        release_state = Path(
            plan["release_state_target"]
        )

        bootstrap_target = Path(
            plan["bootstrap_target"]
        )

        launcher_target = Path(
            plan["launcher_target"]
        )

        identity_target = Path(
            plan["identity_target"]
        )

        source_hashes = plan.get(
            "source_hashes"
        )

        release_hashes = plan.get(
            "release_state_hashes"
        )

        if not isinstance(
            source_hashes,
            dict,
        ):
            raise ValueError(
                "source hash map invalid"
            )

        if not isinstance(
            release_hashes,
            dict,
        ):
            raise ValueError(
                "release-state hash map invalid"
            )

        manifest_name = (
            f"MEMORIA-{release}.payload.sha256"
        )

        if manifest_name not in release_hashes:
            raise ValueError(
                "bound payload manifest missing"
            )

        expected_manifest_sha = (
            _valid_sha256(
                release_hashes[
                    manifest_name
                ]
            )
        )

        integrity_sha = _valid_sha256(
            source_hashes[
                _INTEGRITY_SOURCE
            ]
        )

        launcher_sha = _valid_sha256(
            source_hashes[
                _LAUNCHER_SOURCE
            ]
        )

        # -------------------------------------------------
        # PRE-VERIFY: exact inert runtime state
        # -------------------------------------------------

        _assert_target_still_absent(
            identity_target,
            "installed identity",
        )

        _verify_existing_release_state(
            release_state,
            release_hashes,
        )

        _verify_existing_regular_target(
            bootstrap_target,
            integrity_sha,
            mode=0o644,
        )

        _verify_existing_regular_target(
            launcher_target,
            launcher_sha,
            mode=0o755,
        )

        # Read the exact installed verifier bytes through
        # the verified absolute parent chain + O_NOFOLLOW.
        verifier_bytes = (
            _read_verified_absolute_regular_file(
                bootstrap_target,
                integrity_sha,
            )
        )

        # Metadata/hash must still be exact after the read.
        _verify_existing_regular_target(
            bootstrap_target,
            integrity_sha,
            mode=0o644,
        )

        code = compile(
            verifier_bytes,
            str(bootstrap_target),
            "exec",
        )

        namespace = {
            "__name__":
                "memoria_pre_activation_runtime_integrity",
            "__file__":
                str(bootstrap_target),
            "__package__":
                None,
        }

        exec(
            code,
            namespace,
            namespace,
        )

        verify = namespace.get(
            "verify"
        )

        if not callable(verify):
            raise ValueError(
                "staged verifier has no callable verify()"
            )

        verifier_fingerprint = namespace.get(
            "EXPECTED_FINGERPRINT"
        )

        if verifier_fingerprint != (
            _PRE_ACTIVATION_EXPECTED_FINGERPRINT
        ):
            raise ValueError(
                "staged verifier fingerprint constant mismatch"
            )

        verifier_keyring = namespace.get(
            "CANONICAL_KEYRING"
        )

        if (
            verifier_keyring is None
            or Path(verifier_keyring)
            != _PRE_ACTIVATION_TRUST_ANCHOR
        ):
            raise ValueError(
                "staged verifier canonical keyring mismatch"
            )

        integrity_result = verify(
            project_root,
            release_state,
            manifest_name,
            _PRE_ACTIVATION_TRUST_ANCHOR,
        )

        if not isinstance(
            integrity_result,
            dict,
        ):
            raise ValueError(
                "Runtime Integrity result invalid"
            )

        result["fingerprint"] = (
            integrity_result.get(
                "fingerprint"
            )
        )

        result["manifest_sha256"] = (
            integrity_result.get(
                "manifest_sha256"
            )
        )

        result["entries"] = (
            integrity_result.get(
                "entries"
            )
        )

        result["match"] = (
            integrity_result.get(
                "match"
            )
        )

        result["drift"] = (
            integrity_result.get(
                "drift"
            )
        )

        result["missing"] = (
            integrity_result.get(
                "missing"
            )
        )

        result["unsafe"] = (
            integrity_result.get(
                "unsafe"
            )
        )

        if integrity_result.get(
            "ok"
        ) is not True:
            raise ValueError(
                "signed runtime payload did not verify"
            )

        if result["fingerprint"] != (
            _PRE_ACTIVATION_EXPECTED_FINGERPRINT
        ):
            raise ValueError(
                "verified signer fingerprint mismatch"
            )

        if result["fingerprint"] != signer:
            raise ValueError(
                "verified signer differs from bound plan"
            )

        if result["manifest_sha256"] != (
            expected_manifest_sha
        ):
            raise ValueError(
                "verified manifest differs from bound plan"
            )

        if (
            not isinstance(
                result["entries"],
                int,
            )
            or result["entries"] <= 0
            or result["match"]
            != result["entries"]
        ):
            raise ValueError(
                "payload entry/match count invalid"
            )

        if result["drift"] != []:
            raise ValueError(
                "payload drift detected"
            )

        if result["missing"] != []:
            raise ValueError(
                "payload missing entries detected"
            )

        if result["unsafe"] != []:
            raise ValueError(
                "payload unsafe entries detected"
            )

        # -------------------------------------------------
        # POST-VERIFY: verifier execution must not have
        # altered the inert staging targets or Identity.
        # -------------------------------------------------

        _assert_target_still_absent(
            identity_target,
            "installed identity",
        )

        _verify_existing_release_state(
            release_state,
            release_hashes,
        )

        _verify_existing_regular_target(
            bootstrap_target,
            integrity_sha,
            mode=0o644,
        )

        _verify_existing_regular_target(
            launcher_target,
            launcher_sha,
            mode=0o755,
        )

        result["verified"] = True
        result["pre_activation_status"] = (
            "PRE-ACTIVATION INTEGRITY VERIFIED"
        )

        result["reason"] = (
            "Exact staged Runtime Integrity verifier "
            "validated release signature, bound manifest, "
            "and complete payload. Installed Identity "
            "remains absent."
        )

        return 0, result

    except Exception as exc:
        result["pre_activation_status"] = (
            "PRE-ACTIVATION INTEGRITY BLOCKED"
        )

        result["reason"] = (
            "Pre-activation Runtime Integrity failed: "
            f"{type(exc).__name__}. "
            "Installed Identity must remain absent."
        )

        return 11, result



_IDENTITY_SCHEMA = (
    "memoria-installed-runtime-v0.1"
)

_CANONICAL_RUNTIME_RELEASE_BASE = Path(
    "/usr/local/share/memoria/release"
)

_CANONICAL_RUNTIME_IDENTITY = Path(
    "/var/local/memoria/installed-runtime.json"
)


def _build_runtime_identity_bytes(
    plan,
):
    if not isinstance(plan, dict):
        raise TypeError(
            "runtime identity plan must be dict"
        )

    project_text = plan.get(
        "project_root"
    )

    release = plan.get(
        "active_release"
    )

    if not isinstance(
        project_text,
        str,
    ):
        raise ValueError(
            "identity project_root invalid"
        )

    project_root = Path(
        project_text
    )

    if (
        not project_root.is_absolute()
        or ".." in project_root.parts
        or "\x00" in project_text
    ):
        raise ValueError(
            "identity project_root invalid"
        )

    if (
        not isinstance(release, str)
        or not release
        or "/" in release
        or "\\" in release
        or "\x00" in release
    ):
        raise ValueError(
            "identity active_release invalid"
        )

    identity = {
        "schema_version":
            _IDENTITY_SCHEMA,
        "project_root":
            project_text,
        "active_release":
            release,
    }

    return (
        json.dumps(
            identity,
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    ).encode("utf-8")


def _load_exact_staged_integrity_namespace(
    plan,
):
    if not isinstance(plan, dict):
        raise TypeError(
            "runtime plan must be dict"
        )

    source_hashes = plan.get(
        "source_hashes"
    )

    if not isinstance(
        source_hashes,
        dict,
    ):
        raise ValueError(
            "source hash map invalid"
        )

    bootstrap_target = Path(
        plan["bootstrap_target"]
    )

    integrity_sha = _valid_sha256(
        source_hashes[
            _INTEGRITY_SOURCE
        ]
    )

    _verify_existing_regular_target(
        bootstrap_target,
        integrity_sha,
        mode=0o644,
    )

    verifier_bytes = (
        _read_verified_absolute_regular_file(
            bootstrap_target,
            integrity_sha,
        )
    )

    code = compile(
        verifier_bytes,
        str(bootstrap_target),
        "exec",
    )

    namespace = {
        "__name__":
            "memoria_post_activation_runtime_integrity",
        "__file__":
            str(bootstrap_target),
        "__package__":
            None,
    }

    exec(
        code,
        namespace,
        namespace,
    )

    verify_installed = namespace.get(
        "_verify_installed_runtime_with_paths"
    )

    if not callable(
        verify_installed
    ):
        raise ValueError(
            "staged verifier lacks installed-runtime verifier"
        )

    if namespace.get(
        "IDENTITY_SCHEMA"
    ) != _IDENTITY_SCHEMA:
        raise ValueError(
            "staged verifier Identity schema mismatch"
        )

    if namespace.get(
        "EXPECTED_FINGERPRINT"
    ) != _PRE_ACTIVATION_EXPECTED_FINGERPRINT:
        raise ValueError(
            "staged verifier fingerprint mismatch"
        )

    if Path(
        namespace.get(
            "CANONICAL_KEYRING"
        )
    ) != _PRE_ACTIVATION_TRUST_ANCHOR:
        raise ValueError(
            "staged verifier canonical keyring mismatch"
        )

    if Path(
        namespace.get(
            "CANONICAL_RELEASE_BASE"
        )
    ) != _CANONICAL_RUNTIME_RELEASE_BASE:
        raise ValueError(
            "staged verifier canonical release base mismatch"
        )

    _verify_existing_regular_target(
        bootstrap_target,
        integrity_sha,
        mode=0o644,
    )

    return namespace


def _commit_runtime_identity_and_postverify_with_paths(
    handoff,
    *,
    release_base,
):
    """
    Private testable Identity commit primitive.

    release_base is injectable only for isolated regression
    fixtures. Trust Anchor remains canonical/fixed.
    """

    result = {
        "activation_status":
            "BLOCKED",
        "identity_published":
            False,
        "post_activation_verified":
            False,
        "identity_sha256":
            None,
        "fingerprint":
            None,
        "entries":
            None,
        "match":
            None,
        "drift":
            None,
        "missing":
            None,
        "unsafe":
            None,
        "reason":
            None,
    }

    identity_target = None
    identity_sha = None

    try:
        if (
            not isinstance(handoff, dict)
            or set(handoff)
            != _EXECUTION_HANDOFF_KEYS
        ):
            raise ValueError(
                "execution handoff invalid"
            )

        plan = handoff.get(
            "plan"
        )

        if not isinstance(plan, dict):
            raise ValueError(
                "execution plan invalid"
            )

        release_base = Path(
            release_base
        )

        if (
            not release_base.is_absolute()
            or ".." in release_base.parts
        ):
            raise ValueError(
                "release base invalid"
            )

        release = plan.get(
            "active_release"
        )

        release_state = Path(
            plan["release_state_target"]
        )

        if release_state != (
            release_base / release
        ):
            raise ValueError(
                "release-state / release-base binding mismatch"
            )

        identity_target = Path(
            plan["identity_target"]
        )

        # Re-run the COMPLETE cryptographic pre-activation
        # verification immediately before Identity commit.
        pre_status, pre_result = (
            _verify_pre_activation_runtime_integrity(
                handoff
            )
        )

        if (
            pre_status != 0
            or pre_result.get(
                "verified"
            ) is not True
        ):
            result["reason"] = (
                "Final pre-Identity Runtime Integrity "
                "verification failed."
            )
            return 12, result

        source_hashes = plan[
            "source_hashes"
        ]

        release_hashes = plan[
            "release_state_hashes"
        ]

        integrity_sha = _valid_sha256(
            source_hashes[
                _INTEGRITY_SOURCE
            ]
        )

        launcher_sha = _valid_sha256(
            source_hashes[
                _LAUNCHER_SOURCE
            ]
        )

        # One final exact staging-state check immediately
        # before exposing the activation anchor.
        _verify_existing_release_state(
            release_state,
            release_hashes,
        )

        _verify_existing_regular_target(
            Path(
                plan["bootstrap_target"]
            ),
            integrity_sha,
            mode=0o644,
        )

        _verify_existing_regular_target(
            Path(
                plan["launcher_target"]
            ),
            launcher_sha,
            mode=0o755,
        )

        _assert_target_still_absent(
            identity_target,
            "installed identity",
        )

        identity_bytes = (
            _build_runtime_identity_bytes(
                plan
            )
        )

        identity_sha = hashlib.sha256(
            identity_bytes
        ).hexdigest()

        result["identity_sha256"] = (
            identity_sha
        )

        parent_fd = (
            _ensure_target_parent_directory(
                identity_target
            )
        )

        try:
            # Parent creation itself may race with another
            # actor, so check Identity again afterwards.
            _assert_target_still_absent(
                identity_target,
                "installed identity",
            )

            _publish_verified_regular_file_at(
                parent_fd,
                identity_target.name,
                identity_bytes,
                identity_sha,
                mode=0o644,
            )

        finally:
            os.close(parent_fd)

        result["identity_published"] = True

        _verify_existing_regular_target(
            identity_target,
            identity_sha,
            mode=0o644,
        )

        # Post-activation verification uses the exact
        # installed/staged Runtime Integrity verifier again.
        namespace = (
            _load_exact_staged_integrity_namespace(
                plan
            )
        )

        verify_installed = namespace[
            "_verify_installed_runtime_with_paths"
        ]

        post = verify_installed(
            identity_target,
            release_base,
            _PRE_ACTIVATION_TRUST_ANCHOR,
        )

        if not isinstance(post, dict):
            raise ValueError(
                "post-activation result invalid"
            )

        result["fingerprint"] = post.get(
            "fingerprint"
        )

        result["entries"] = post.get(
            "entries"
        )

        result["match"] = post.get(
            "match"
        )

        result["drift"] = post.get(
            "drift"
        )

        result["missing"] = post.get(
            "missing"
        )

        result["unsafe"] = post.get(
            "unsafe"
        )

        manifest_name = (
            f"MEMORIA-{release}.payload.sha256"
        )

        if post.get("ok") is not True:
            raise ValueError(
                "installed runtime did not verify"
            )

        if post.get(
            "fingerprint"
        ) != _PRE_ACTIVATION_EXPECTED_FINGERPRINT:
            raise ValueError(
                "post-activation signer mismatch"
            )

        if post.get(
            "fingerprint"
        ) != plan.get(
            "signer_fingerprint"
        ):
            raise ValueError(
                "post-activation signer differs from bound plan"
            )

        if post.get(
            "manifest_sha256"
        ) != _valid_sha256(
            release_hashes[
                manifest_name
            ]
        ):
            raise ValueError(
                "post-activation manifest mismatch"
            )

        if post.get(
            "project_root"
        ) != plan.get(
            "project_root"
        ):
            raise ValueError(
                "post-activation project_root mismatch"
            )

        if post.get(
            "active_release"
        ) != release:
            raise ValueError(
                "post-activation release mismatch"
            )

        if post.get(
            "release_state"
        ) != str(
            release_state
        ):
            raise ValueError(
                "post-activation release-state mismatch"
            )

        if post.get(
            "manifest_name"
        ) != manifest_name:
            raise ValueError(
                "post-activation manifest-name mismatch"
            )

        if (
            not isinstance(
                post.get("entries"),
                int,
            )
            or post["entries"] <= 0
            or post.get("match")
            != post["entries"]
        ):
            raise ValueError(
                "post-activation entry count mismatch"
            )

        if post.get("drift") != []:
            raise ValueError(
                "post-activation drift detected"
            )

        if post.get("missing") != []:
            raise ValueError(
                "post-activation missing payload"
            )

        if post.get("unsafe") != []:
            raise ValueError(
                "post-activation unsafe payload"
            )

        # Identity itself must remain byte-exact after
        # post-activation verification.
        _verify_existing_regular_target(
            identity_target,
            identity_sha,
            mode=0o644,
        )

        result["post_activation_verified"] = (
            True
        )

        result["activation_status"] = (
            "ACTIVATED AND VERIFIED"
        )

        result["reason"] = (
            "Installed Identity was atomically committed "
            "last and the exact staged Runtime Integrity "
            "verifier validated the activated runtime."
        )

        return 0, result

    except FileExistsError:
        result["activation_status"] = (
            "IDENTITY COMMIT BLOCKED"
        )

        result["reason"] = (
            "Installed Identity appeared before atomic "
            "commit. Existing Identity was not overwritten "
            "or adopted."
        )

        return 13, result

    except Exception as exc:
        # If Identity was already published, NEVER remove it.
        # A post-publish failure requires explicit Admin action.
        exact_identity_present = False

        if (
            identity_target is not None
            and identity_sha is not None
        ):
            try:
                exact_identity_present = (
                    _verify_existing_regular_target(
                        identity_target,
                        identity_sha,
                        mode=0o644,
                    )
                    == identity_sha
                )
            except Exception:
                exact_identity_present = False

        if (
            result["identity_published"]
            or exact_identity_present
        ):
            result["identity_published"] = (
                True
            )

            result["activation_status"] = (
                "ACTIVATED BUT POST-VERIFY FAILED"
            )

            result["reason"] = (
                "Installed Identity is present, but "
                "post-activation verification failed: "
                f"{type(exc).__name__}. "
                "No automatic rollback, deletion, "
                "or retry is allowed."
            )

            return 14, result

        result["activation_status"] = (
            "IDENTITY COMMIT ERROR"
        )

        result["reason"] = (
            "Identity commit failed before a verified "
            "activation anchor was established: "
            f"{type(exc).__name__}. "
            "No automatic retry is allowed."
        )

        return 13, result


def _commit_runtime_identity_and_postverify(
    handoff,
):
    """
    Production wrapper: no public path overrides.
    """

    if (
        not isinstance(handoff, dict)
        or not isinstance(
            handoff.get("plan"),
            dict,
        )
    ):
        return 13, {
            "activation_status":
                "IDENTITY COMMIT BLOCKED",
            "identity_published":
                False,
            "post_activation_verified":
                False,
            "reason":
                "Canonical activation handoff invalid.",
        }

    plan = handoff["plan"]

    release = plan.get(
        "active_release"
    )

    if (
        Path(
            plan.get(
                "identity_target",
                "",
            )
        )
        != _CANONICAL_RUNTIME_IDENTITY
        or Path(
            plan.get(
                "release_state_target",
                "",
            )
        )
        != (
            _CANONICAL_RUNTIME_RELEASE_BASE
            / str(release)
        )
    ):
        return 13, {
            "activation_status":
                "IDENTITY COMMIT BLOCKED",
            "identity_published":
                False,
            "post_activation_verified":
                False,
            "reason":
                "Canonical activation target binding mismatch.",
        }

    return (
        _commit_runtime_identity_and_postverify_with_paths(
            handoff,
            release_base=(
                _CANONICAL_RUNTIME_RELEASE_BASE
            ),
        )
    )


def run_runtime_bootstrap_attempt(
    authorization_store,
    authorization,
    bundle_context,
):
    """
    Public production facade for exactly one authorized
    runtime-bootstrap execution attempt.

    Approval and authorization issuance remain separate
    stages and are not performed here.

    The process-local ExecutionTicket never leaves this
    facade. No automatic retry or rollback is performed.
    """

    from memoria_runtime_bootstrap_approval import (
        runtime_bootstrap_plan_is_approvable,
    )
    from memoria_runtime_bootstrap_plan import (
        build_runtime_bootstrap_plan,
        verify_runtime_bootstrap_plan_identity,
    )

    execution_store = (
        RuntimeBootstrapExecutionHandoffStore()
    )

    (
        prepare_status,
        prepare_result,
        ticket,
    ) = _prepare_runtime_bootstrap_handoff(
        authorization_store,
        authorization,
        bundle_context,
        execution_store=execution_store,
        plan_builder=build_runtime_bootstrap_plan,
        plan_identity_verifier=(
            verify_runtime_bootstrap_plan_identity
        ),
        plan_approvable=(
            runtime_bootstrap_plan_is_approvable
        ),
    )

    result = {
        "schema_version": SCHEMA_VERSION,
        "runner_status": prepare_result.get(
            "runner_status",
            "BLOCKED",
        ),
        "authorization_consumed": (
            prepare_result.get(
                "authorization_consumed"
            )
            is True
        ),
        "execution_authorized": (
            prepare_result.get(
                "execution_authorized"
            )
            is True
        ),
        "execution_performed": False,
        "approval_id": prepare_result.get(
            "approval_id"
        ),
        "plan_sha256": prepare_result.get(
            "plan_sha256"
        ),
        "reason": prepare_result.get(
            "reason"
        ),
        "execution_result": None,
    }

    if (
        prepare_status != 0
        or ticket is None
    ):
        return prepare_status, result

    execute_status, execute_result = (
        _execute_runtime_bootstrap_write_layer(
            execution_store,
            ticket,
        )
    )

    result["runner_status"] = (
        execute_result.get(
            "runner_status",
            "BLOCKED",
        )
    )

    result["execution_performed"] = (
        execute_result.get(
            "execution_performed"
        )
        is True
    )

    result["approval_id"] = (
        execute_result.get("approval_id")
        or result["approval_id"]
    )

    result["plan_sha256"] = (
        execute_result.get("plan_sha256")
        or result["plan_sha256"]
    )

    result["reason"] = execute_result.get(
        "reason",
        result["reason"],
    )

    result["execution_result"] = (
        deepcopy(execute_result)
    )

    return execute_status, result
