#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Callable


SCHEMA_VERSION = "memoria-trust-anchor-plan-v0.1"

DEFAULT_SOURCE = Path(
    "release/memoria-release-keyring.gpg"
)
DEFAULT_SIGNATURE = Path(
    "release/0.2.1/SHA256SUMS.sig"
)
DEFAULT_SUMS = Path(
    "release/0.2.1/SHA256SUMS"
)
DEFAULT_TARGET = Path(
    "/usr/share/keyrings/memoria-release.gpg"
)

EXPECTED_SOURCE_SHA256 = (
    "fa63c650d381ac85e5b6f49460e3c7e"
    "e3999f2ac705ad982c237d037a69ff8f6"
)
EXPECTED_FINGERPRINT = (
    "2A43DDB1EB6CAE0E011D8C688F3BBFD776DF59A3"
)

REQUIRED_TARGET_MODE = 0o644
REQUIRED_TARGET_UID = 0
REQUIRED_TARGET_GID = 0

SignatureVerifier = Callable[
    [Path, Path, Path],
    tuple[bool, str | None, str | None],
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for chunk in iter(
            lambda: handle.read(1024 * 1024),
            b"",
        ):
            digest.update(chunk)

    return digest.hexdigest()


def _safe_regular_file(
    path: Path,
) -> tuple[bool, str | None]:
    if path.is_symlink():
        return False, f"Symlink rejected: {path}"

    if not path.is_file():
        return False, f"Regular file required: {path}"

    return True, None


def _default_signature_verifier(
    public_key: Path,
    signature: Path,
    sums: Path,
) -> tuple[bool, str | None, str | None]:
    gpgv = Path("/usr/bin/gpgv")

    if not gpgv.is_file() or gpgv.is_symlink():
        return (
            False,
            None,
            "Canonical /usr/bin/gpgv unavailable.",
        )

    with tempfile.TemporaryDirectory(
        prefix="memoria-trust-plan-"
    ) as temporary:
        home = Path(temporary)
        home.chmod(0o700)

        completed = subprocess.run(
            [
                str(gpgv),
                "--homedir",
                str(home),
                "--keyring",
                str(public_key.resolve()),
                "--status-fd",
                "1",
                str(signature.resolve()),
                str(sums.resolve()),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            close_fds=True,
        )

    fingerprint = None

    for line in completed.stdout.splitlines():
        fields = line.split()

        if (
            len(fields) >= 3
            and fields[0] == "[GNUPG:]"
            and fields[1] == "VALIDSIG"
        ):
            fingerprint = fields[2]
            break

    if completed.returncode != 0:
        return (
            False,
            fingerprint,
            "gpgv rejected release signature.",
        )

    if fingerprint is None:
        return (
            False,
            None,
            "gpgv returned no VALIDSIG fingerprint.",
        )

    return True, fingerprint, None


def _target_state(
    target: Path,
    source_sha256: str,
) -> tuple[
    str,
    str | None,
    str | None,
    int | None,
    int | None,
    str | None,
]:
    if target.is_symlink():
        metadata = target.lstat()
        return (
            "BLOCKED",
            None,
            f"{stat.S_IMODE(metadata.st_mode):04o}",
            metadata.st_uid,
            metadata.st_gid,
            "Existing target is a symlink.",
        )

    if not target.exists():
        return (
            "ABSENT",
            None,
            None,
            None,
            None,
            None,
        )

    metadata = target.lstat()
    target_mode = f"{stat.S_IMODE(metadata.st_mode):04o}"
    target_uid = metadata.st_uid
    target_gid = metadata.st_gid

    if not target.is_file():
        return (
            "BLOCKED",
            None,
            target_mode,
            target_uid,
            target_gid,
            "Existing target is not a regular file.",
        )

    target_sha256 = sha256_file(target)

    if target_sha256 == source_sha256:
        if (
            target_mode != f"{REQUIRED_TARGET_MODE:04o}"
            or target_uid != REQUIRED_TARGET_UID
            or target_gid != REQUIRED_TARGET_GID
        ):
            return (
                "BLOCKED",
                target_sha256,
                target_mode,
                target_uid,
                target_gid,
                "Identical trust anchor content has "
                "unexpected metadata.",
            )

        return (
            "ALREADY INSTALLED",
            target_sha256,
            target_mode,
            target_uid,
            target_gid,
            None,
        )

    return (
        "BLOCKED",
        target_sha256,
        target_mode,
        target_uid,
        target_gid,
        "Different trust anchor already exists.",
    )


def _plan_sha256(result: dict) -> str:
    identity = {
        key: result.get(key)
        for key in (
            "source_path",
            "source_sha256",
            "source_fingerprint",
            "signature_path",
            "signature_sha256",
            "sums_path",
            "sums_sha256",
            "target_path",
            "target_state",
            "target_sha256",
            "target_mode",
            "target_uid",
            "target_gid",
            "required_target_mode",
            "required_target_uid",
            "required_target_gid",
        )
    }

    encoded = json.dumps(
        identity,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")

    return hashlib.sha256(encoded).hexdigest()


def verify_trust_anchor_plan_identity(
    plan: dict,
) -> bool:
    if not isinstance(plan, dict):
        return False

    stored_sha256 = plan.get("plan_sha256")

    if not isinstance(stored_sha256, str):
        return False

    if (
        len(stored_sha256) != 64
        or any(
            char not in "0123456789abcdef"
            for char in stored_sha256
        )
    ):
        return False

    try:
        expected_sha256 = _plan_sha256(plan)
    except (TypeError, ValueError):
        return False

    return stored_sha256 == expected_sha256


def build_trust_anchor_plan(
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
    signature_verifier: SignatureVerifier = (
        _default_signature_verifier
    ),
) -> dict:
    result = {
        "schema_version": SCHEMA_VERSION,
        "plan_status": "BLOCKED",
        "approvable": False,
        "system_change_allowed": False,
        "execution_performed": False,
        "source_path": str(source),
        "source_sha256": None,
        "source_fingerprint": None,
        "signature_path": str(signature),
        "signature_sha256": None,
        "sums_path": str(sums),
        "sums_sha256": None,
        "target_path": str(target),
        "target_state": None,
        "target_sha256": None,
        "target_mode": None,
        "target_uid": None,
        "target_gid": None,
        "required_target_mode": (
            f"{REQUIRED_TARGET_MODE:04o}"
        ),
        "required_target_uid": REQUIRED_TARGET_UID,
        "required_target_gid": REQUIRED_TARGET_GID,
        "plan_sha256": None,
        "reason": None,
    }

    for path, label in (
        (source, "source"),
        (signature, "signature"),
        (sums, "SHA256SUMS"),
    ):
        safe, reason = _safe_regular_file(path)

        if not safe:
            result["reason"] = f"{label}: {reason}"
            return result

    source_sha256 = sha256_file(source)
    result["source_sha256"] = source_sha256
    result["signature_sha256"] = sha256_file(
        signature
    )
    result["sums_sha256"] = sha256_file(sums)

    if source_sha256 != expected_source_sha256:
        result["reason"] = "Release public-key SHA-256 drift."
        return result

    verified, fingerprint, reason = signature_verifier(
        source,
        signature,
        sums,
    )

    result["source_fingerprint"] = fingerprint

    if verified is not True:
        result["reason"] = (
            reason or "Release signature verification failed."
        )
        return result

    if fingerprint != expected_fingerprint:
        result["reason"] = (
            "Release signer fingerprint drift."
        )
        return result

    (
        target_state,
        target_sha256,
        target_mode,
        target_uid,
        target_gid,
        target_reason,
    ) = _target_state(
        target,
        source_sha256,
    )

    result["target_state"] = target_state
    result["target_sha256"] = target_sha256
    result["target_mode"] = target_mode
    result["target_uid"] = target_uid
    result["target_gid"] = target_gid
    result["plan_sha256"] = _plan_sha256(result)

    if target_state == "ABSENT":
        result["plan_status"] = "READY FOR APPROVAL"
        result["approvable"] = True
        result["reason"] = (
            "Verified trust anchor may be proposed "
            "for explicit approval."
        )
        return result

    if target_state == "ALREADY INSTALLED":
        result["plan_status"] = "ALREADY INSTALLED"
        result["reason"] = (
            "Identical trust anchor already exists."
        )
        return result

    result["reason"] = (
        target_reason
        or "Target state is not eligible."
    )

    return result
