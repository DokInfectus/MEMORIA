#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path


SCHEMA_VERSION = (
    "memoria-trust-anchor-rebootstrap-plan-v0.1"
)

DEFAULT_SOURCE = Path(
    "release/memoria-release-keyring.gpg"
)
DEFAULT_TARGET = Path(
    "/usr/share/keyrings/memoria-release.gpg"
)

EXPECTED_CURRENT_SHA256 = (
    "022a7c4de69803fd7f9fee6e09c5633b2"
    "afa822710135f1f1602e6e799443806"
)
EXPECTED_REPLACEMENT_SHA256 = (
    "fa63c650d381ac85e5b6f49460e3c7e"
    "e3999f2ac705ad982c237d037a69ff8f6"
)

HISTORICAL_FINGERPRINT = (
    "E27B877C3B5AB6C74C33399C9E82CC6E190E5E85"
)
CURRENT_FINGERPRINT = (
    "2A43DDB1EB6CAE0E011D8C688F3BBFD776DF59A3"
)

REQUIRED_TARGET_MODE = 0o644
REQUIRED_TARGET_UID = 0
REQUIRED_TARGET_GID = 0

TRANSITION_AUTHORITY = "EXPLICIT ADMIN REBOOTSTRAP"


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


def _plan_sha256(result: dict) -> str:
    fields = (
        "transition_authority",
        "source_path",
        "source_sha256",
        "target_path",
        "target_state",
        "target_sha256",
        "target_mode",
        "target_uid",
        "target_gid",
        "expected_current_sha256",
        "expected_replacement_sha256",
        "historical_fingerprint",
        "current_fingerprint",
        "required_target_mode",
        "required_target_uid",
        "required_target_gid",
    )

    identity = {
        field: result.get(field)
        for field in fields
    }

    encoded = json.dumps(
        identity,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")

    return hashlib.sha256(encoded).hexdigest()


def verify_rebootstrap_plan_identity(
    plan: dict,
) -> bool:
    if not isinstance(plan, dict):
        return False

    stored = plan.get("plan_sha256")

    if (
        not isinstance(stored, str)
        or len(stored) != 64
        or any(
            char not in "0123456789abcdef"
            for char in stored
        )
    ):
        return False

    try:
        return stored == _plan_sha256(plan)
    except (TypeError, ValueError):
        return False


def build_trust_anchor_rebootstrap_plan(
    *,
    source: Path = DEFAULT_SOURCE,
    target: Path = DEFAULT_TARGET,
    expected_current_sha256: str = (
        EXPECTED_CURRENT_SHA256
    ),
    expected_replacement_sha256: str = (
        EXPECTED_REPLACEMENT_SHA256
    ),
    historical_fingerprint: str = (
        HISTORICAL_FINGERPRINT
    ),
    current_fingerprint: str = CURRENT_FINGERPRINT,
) -> dict:
    result = {
        "schema_version": SCHEMA_VERSION,
        "plan_status": "BLOCKED",
        "approvable": False,
        "system_change_allowed": False,
        "execution_performed": False,
        "transition_authority": TRANSITION_AUTHORITY,
        "source_path": str(source),
        "source_sha256": None,
        "target_path": str(target),
        "target_state": None,
        "target_sha256": None,
        "target_mode": None,
        "target_uid": None,
        "target_gid": None,
        "expected_current_sha256": (
            expected_current_sha256
        ),
        "expected_replacement_sha256": (
            expected_replacement_sha256
        ),
        "historical_fingerprint": (
            historical_fingerprint
        ),
        "current_fingerprint": current_fingerprint,
        "required_target_mode": (
            f"{REQUIRED_TARGET_MODE:04o}"
        ),
        "required_target_uid": REQUIRED_TARGET_UID,
        "required_target_gid": REQUIRED_TARGET_GID,
        "plan_sha256": None,
        "reason": None,
    }

    safe, reason = _safe_regular_file(source)

    if not safe:
        result["reason"] = f"source: {reason}"
        return result

    source_sha256 = sha256_file(source)
    result["source_sha256"] = source_sha256

    if source_sha256 != expected_replacement_sha256:
        result["reason"] = (
            "Replacement Trust Anchor SHA-256 drift."
        )
        return result

    if target.is_symlink():
        result["target_state"] = "BLOCKED"
        result["reason"] = (
            "Existing target is a symlink."
        )
        result["plan_sha256"] = _plan_sha256(result)
        return result

    if not target.exists():
        result["target_state"] = "ABSENT"
        result["reason"] = (
            "Admin rebootstrap requires the known "
            "existing Trust Anchor."
        )
        result["plan_sha256"] = _plan_sha256(result)
        return result

    metadata = target.lstat()

    result["target_mode"] = (
        f"{stat.S_IMODE(metadata.st_mode):04o}"
    )
    result["target_uid"] = metadata.st_uid
    result["target_gid"] = metadata.st_gid

    if not stat.S_ISREG(metadata.st_mode):
        result["target_state"] = "BLOCKED"
        result["reason"] = (
            "Existing target is not a regular file."
        )
        result["plan_sha256"] = _plan_sha256(result)
        return result

    target_sha256 = sha256_file(target)
    result["target_sha256"] = target_sha256

    metadata_ok = (
        stat.S_IMODE(metadata.st_mode)
        == REQUIRED_TARGET_MODE
        and metadata.st_uid == REQUIRED_TARGET_UID
        and metadata.st_gid == REQUIRED_TARGET_GID
    )

    if not metadata_ok:
        result["target_state"] = "BLOCKED"
        result["reason"] = (
            "Existing Trust Anchor metadata drift."
        )
        result["plan_sha256"] = _plan_sha256(result)
        return result

    if target_sha256 == expected_replacement_sha256:
        result["target_state"] = (
            "ALREADY REBOOTSTRAPPED"
        )
        result["plan_status"] = (
            "ALREADY REBOOTSTRAPPED"
        )
        result["reason"] = (
            "Replacement Trust Anchor already installed."
        )
        result["plan_sha256"] = _plan_sha256(result)
        return result

    if target_sha256 != expected_current_sha256:
        result["target_state"] = "BLOCKED"
        result["reason"] = (
            "Existing Trust Anchor does not match "
            "the bound pre-rebootstrap state."
        )
        result["plan_sha256"] = _plan_sha256(result)
        return result

    result["target_state"] = (
        "EXPECTED CURRENT ANCHOR"
    )
    result["plan_status"] = (
        "READY FOR ADMIN APPROVAL"
    )
    result["approvable"] = True
    result["reason"] = (
        "Exact pre-rebootstrap Trust Anchor and "
        "replacement candidate verified."
    )
    result["plan_sha256"] = _plan_sha256(result)

    return result
