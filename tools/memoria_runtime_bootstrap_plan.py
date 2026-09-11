#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
from pathlib import Path
from typing import Any, Callable


SCHEMA_VERSION = (
    "memoria-runtime-bootstrap-plan-v0.1"
)

CONTEXT_SCHEMA = (
    "memoria-release-bundle-context-v0.1"
)

EXPECTED_FINGERPRINT = (
    "2A43DDB1EB6CAE0E011D8C688F3BBFD776DF59A3"
)

CANONICAL_TRUST_ANCHOR = Path(
    "/usr/share/keyrings/memoria-release.gpg"
)

CANONICAL_RELEASE_BASE = Path(
    "/usr/local/share/memoria/release"
)

CANONICAL_BOOTSTRAP_TARGET = Path(
    "/usr/local/lib/memoria/"
    "memoria_release_runtime_integrity.py"
)

CANONICAL_LAUNCHER_TARGET = Path(
    "/usr/local/bin/memoria"
)

CANONICAL_IDENTITY_TARGET = Path(
    "/var/local/memoria/installed-runtime.json"
)

CANONICAL_GPGV = Path(
    "/usr/bin/gpgv"
)

REQUIRED_PAYLOAD_SOURCES = (
    "tools/memoria_release_runtime_integrity.py",
    "tools/memoria_runtime_launcher.py",
    "tools/memoria_runtime_bootstrap_plan.py",
)

CONTEXT_KEYS = {
    "schema_version",
    "active_release",
    "bundle_dir",
    "project_root",
}

SHA256_RE = re.compile(
    r"^[0-9a-f]{64}$"
)

RELEASE_RE = re.compile(
    r"^[0-9]+\.[0-9]+\.[0-9]+"
    r"(?:-(?:alpha|beta|rc[0-9]*))?$"
)

SignatureVerifier = Callable[
    [Path, Path, Path],
    tuple[bool, str | None, str | None],
]


class BootstrapPlanError(RuntimeError):
    pass


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        while True:
            block = handle.read(1024 * 1024)

            if not block:
                break

            digest.update(block)

    return digest.hexdigest()


def _canonical_sha256(value: dict[str, Any]) -> str:
    data = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")

    return _sha256_bytes(data)


def _plan_sha256(plan: dict[str, Any]) -> str:
    payload = {
        key: value
        for key, value in plan.items()
        if key != "plan_sha256"
    }

    return _canonical_sha256(payload)


def verify_runtime_bootstrap_plan_identity(
    plan: dict[str, Any],
) -> bool:
    if not isinstance(plan, dict):
        return False

    digest = plan.get("plan_sha256")

    return (
        isinstance(digest, str)
        and SHA256_RE.fullmatch(digest) is not None
        and digest == _plan_sha256(plan)
    )


def _checked_absolute_path(
    value: Any,
    label: str,
) -> Path:
    if not isinstance(value, str) or not value:
        raise BootstrapPlanError(
            f"{label} must be non-empty string"
        )

    path = Path(value)

    if (
        not path.is_absolute()
        or ".." in path.parts
        or str(path) != value
    ):
        raise BootstrapPlanError(
            f"{label} must be canonical absolute path"
        )

    return path


def _no_symlink_components(
    path: Path,
    *,
    allow_missing: bool,
) -> None:
    current = Path("/")

    for part in path.parts[1:]:
        current = current / part

        try:
            meta = current.lstat()
        except FileNotFoundError:
            if allow_missing:
                return
            raise

        if stat.S_ISLNK(meta.st_mode):
            raise BootstrapPlanError(
                f"symlink path component: {current}"
            )


def _safe_existing_directory(
    path: Path,
    label: str,
) -> None:
    _no_symlink_components(
        path,
        allow_missing=False,
    )

    meta = path.lstat()

    if not stat.S_ISDIR(meta.st_mode):
        raise BootstrapPlanError(
            f"{label} is not directory"
        )


def _safe_regular_file(
    path: Path,
    label: str,
) -> None:
    _no_symlink_components(
        path,
        allow_missing=False,
    )

    meta = path.lstat()

    if not stat.S_ISREG(meta.st_mode):
        raise BootstrapPlanError(
            f"{label} is not regular file"
        )


def _safe_root_file(
    path: Path,
    *,
    mode: int,
    label: str,
) -> None:
    _safe_regular_file(
        path,
        label,
    )

    meta = path.lstat()

    if meta.st_uid != 0 or meta.st_gid != 0:
        raise BootstrapPlanError(
            f"{label} must be root:root"
        )

    if stat.S_IMODE(meta.st_mode) != mode:
        raise BootstrapPlanError(
            f"{label} mode must be {mode:04o}"
        )


def _safe_gpgv() -> None:
    _safe_regular_file(
        CANONICAL_GPGV,
        "canonical gpgv",
    )

    meta = CANONICAL_GPGV.lstat()
    mode = stat.S_IMODE(meta.st_mode)

    if meta.st_uid != 0 or meta.st_gid != 0:
        raise BootstrapPlanError(
            "canonical gpgv must be root:root"
        )

    if mode & 0o022:
        raise BootstrapPlanError(
            "canonical gpgv is group/world writable"
        )

    if not mode & stat.S_IXUSR:
        raise BootstrapPlanError(
            "canonical gpgv is not executable"
        )


def _default_signature_verifier(
    signature: Path,
    sums: Path,
    keyring: Path,
) -> tuple[bool, str | None, str | None]:
    _safe_gpgv()

    completed = subprocess.run(
        [
            str(CANONICAL_GPGV),
            "--status-fd",
            "1",
            "--keyring",
            str(keyring),
            str(signature),
            str(sums),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )

    fingerprints: list[str] = []

    for line in completed.stdout.splitlines():
        parts = line.split()

        if (
            len(parts) >= 3
            and parts[0] == "[GNUPG:]"
            and parts[1] == "VALIDSIG"
        ):
            fingerprints.append(parts[2])

    if completed.returncode != 0:
        return (
            False,
            None,
            "gpgv rejected release signature",
        )

    if len(fingerprints) != 1:
        return (
            False,
            None,
            "gpgv did not return exactly one VALIDSIG",
        )

    return (
        True,
        fingerprints[0],
        None,
    )


def _decode_text(
    path: Path,
    label: str,
) -> str:
    try:
        text = path.read_bytes().decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BootstrapPlanError(
            f"{label} is not valid UTF-8"
        ) from exc

    if not text.endswith("\n"):
        raise BootstrapPlanError(
            f"{label} must end with LF"
        )

    return text


def _parse_sha256sums(
    path: Path,
) -> dict[str, str]:
    text = _decode_text(
        path,
        "SHA256SUMS",
    )

    entries: dict[str, str] = {}

    for line_no, raw in enumerate(
        text.splitlines(),
        start=1,
    ):
        if not raw:
            raise BootstrapPlanError(
                f"SHA256SUMS blank line {line_no}"
            )

        try:
            digest, name = raw.split("  ", 1)
        except ValueError as exc:
            raise BootstrapPlanError(
                f"SHA256SUMS malformed line {line_no}"
            ) from exc

        if SHA256_RE.fullmatch(digest) is None:
            raise BootstrapPlanError(
                f"SHA256SUMS invalid digest line {line_no}"
            )

        if (
            not name
            or "/" in name
            or "\\" in name
            or name in {".", ".."}
        ):
            raise BootstrapPlanError(
                f"SHA256SUMS unsafe name line {line_no}"
            )

        if name in entries:
            raise BootstrapPlanError(
                f"SHA256SUMS duplicate name: {name}"
            )

        entries[name] = digest

    return entries


def _parse_payload_manifest(
    path: Path,
) -> dict[str, str]:
    text = _decode_text(
        path,
        "payload manifest",
    )

    entries: dict[str, str] = {}
    previous: str | None = None

    for line_no, raw in enumerate(
        text.splitlines(),
        start=1,
    ):
        if not raw:
            raise BootstrapPlanError(
                f"payload manifest blank line {line_no}"
            )

        try:
            digest, relative = raw.split("  ", 1)
        except ValueError as exc:
            raise BootstrapPlanError(
                f"payload manifest malformed line {line_no}"
            ) from exc

        if SHA256_RE.fullmatch(digest) is None:
            raise BootstrapPlanError(
                f"payload manifest invalid digest line {line_no}"
            )

        rel = Path(relative)

        if (
            not relative
            or rel.is_absolute()
            or ".." in rel.parts
            or "\\" in relative
            or str(rel) != relative
        ):
            raise BootstrapPlanError(
                f"payload manifest unsafe path line {line_no}"
            )

        if relative in entries:
            raise BootstrapPlanError(
                f"payload manifest duplicate path: {relative}"
            )

        if previous is not None and relative <= previous:
            raise BootstrapPlanError(
                "payload manifest is not strictly sorted"
            )

        previous = relative
        entries[relative] = digest

    if not entries:
        raise BootstrapPlanError(
            "payload manifest is empty"
        )

    return entries


def _verify_existing_target_parent_chain(
    target: Path,
) -> None:
    parent = target.parent
    current = Path("/")

    for part in parent.parts[1:]:
        current = current / part

        try:
            meta = current.lstat()
        except FileNotFoundError:
            return

        if stat.S_ISLNK(meta.st_mode):
            raise BootstrapPlanError(
                f"target parent is symlink: {current}"
            )

        if not stat.S_ISDIR(meta.st_mode):
            raise BootstrapPlanError(
                f"target parent is not directory: {current}"
            )

        if meta.st_uid != 0 or meta.st_gid != 0:
            raise BootstrapPlanError(
                f"target parent is not root:root: {current}"
            )

        if stat.S_IMODE(meta.st_mode) & 0o022:
            raise BootstrapPlanError(
                f"target parent is group/world writable: {current}"
            )


def _file_target_state(
    target: Path,
    expected_sha256: str,
    expected_mode: int,
) -> str:
    try:
        meta = target.lstat()
    except FileNotFoundError:
        return "ABSENT"

    if stat.S_ISLNK(meta.st_mode):
        return "UNSAFE"

    if not stat.S_ISREG(meta.st_mode):
        return "UNSAFE"

    if (
        meta.st_uid != 0
        or meta.st_gid != 0
        or stat.S_IMODE(meta.st_mode) != expected_mode
    ):
        return "UNSAFE"

    if _sha256_file(target) == expected_sha256:
        return "ALREADY STAGED"

    return "DRIFT"


def _identity_target_state(
    target: Path,
) -> str:
    try:
        meta = target.lstat()
    except FileNotFoundError:
        return "ABSENT"

    if stat.S_ISLNK(meta.st_mode):
        return "UNSAFE"

    return "PRESENT"


def _release_state_target_state(
    target: Path,
    expected: dict[str, str],
) -> str:
    try:
        meta = target.lstat()
    except FileNotFoundError:
        return "ABSENT"

    if stat.S_ISLNK(meta.st_mode):
        return "UNSAFE"

    if (
        not stat.S_ISDIR(meta.st_mode)
        or meta.st_uid != 0
        or meta.st_gid != 0
        or stat.S_IMODE(meta.st_mode) != 0o755
    ):
        return "UNSAFE"

    states = [
        _file_target_state(
            target / name,
            digest,
            0o644,
        )
        for name, digest in expected.items()
    ]

    if all(
        state == "ALREADY STAGED"
        for state in states
    ):
        return "ALREADY STAGED"

    if any(
        state == "UNSAFE"
        for state in states
    ):
        return "UNSAFE"

    if any(
        state == "DRIFT"
        for state in states
    ):
        return "DRIFT"

    return "PARTIAL"


def _blocked_result(
    context: Any,
    reason: str,
) -> dict[str, Any]:
    result = {
        "schema_version": SCHEMA_VERSION,
        "plan_status": "BLOCKED",
        "approvable": False,
        "reason": reason,
        "bundle_context": context,
        "bundle_context_sha256": None,
        "active_release": None,
        "project_root": None,
        "bundle_dir": None,
        "signer_fingerprint": None,
        "release_state_target": None,
        "release_state_target_state": None,
        "bootstrap_target": None,
        "bootstrap_target_state": None,
        "launcher_target": None,
        "launcher_target_state": None,
        "identity_target": None,
        "identity_target_state": None,
        "source_hashes": {},
        "release_state_hashes": {},
        "plan_sha256": None,
    }

    result["plan_sha256"] = _plan_sha256(result)

    return result


def _build_runtime_bootstrap_plan_with_paths(
    bundle_context: dict[str, Any],
    *,
    trust_anchor: Path,
    release_base: Path,
    bootstrap_target: Path,
    launcher_target: Path,
    identity_target: Path,
    signature_verifier: SignatureVerifier,
) -> dict[str, Any]:
    if not isinstance(bundle_context, dict):
        return _blocked_result(
            bundle_context,
            "bundle context must be dict",
        )

    result = _blocked_result(
        bundle_context,
        "plan not evaluated",
    )

    try:
        if set(bundle_context) != CONTEXT_KEYS:
            raise BootstrapPlanError(
                "bundle context keys are not exact"
            )

        if (
            bundle_context.get("schema_version")
            != CONTEXT_SCHEMA
        ):
            raise BootstrapPlanError(
                "bundle context schema mismatch"
            )

        release = bundle_context.get(
            "active_release"
        )

        if (
            not isinstance(release, str)
            or RELEASE_RE.fullmatch(release) is None
        ):
            raise BootstrapPlanError(
                "active_release invalid"
            )

        bundle_dir = _checked_absolute_path(
            bundle_context.get("bundle_dir"),
            "bundle_dir",
        )

        project_root = _checked_absolute_path(
            bundle_context.get("project_root"),
            "project_root",
        )

        _safe_existing_directory(
            bundle_dir,
            "bundle_dir",
        )

        _safe_existing_directory(
            project_root,
            "project_root",
        )

        _safe_root_file(
            trust_anchor,
            mode=0o644,
            label="installed Trust Anchor",
        )

        for target in (
            release_base / release,
            bootstrap_target,
            launcher_target,
            identity_target,
        ):
            _verify_existing_target_parent_chain(
                target
            )

        archive_name = (
            f"MEMORIA-{release}.tar.gz"
        )

        manifest_name = (
            f"MEMORIA-{release}.payload.sha256"
        )

        sums = bundle_dir / "SHA256SUMS"
        signature = bundle_dir / "SHA256SUMS.sig"
        archive = bundle_dir / archive_name
        manifest = bundle_dir / manifest_name

        for path, label in (
            (sums, "SHA256SUMS"),
            (signature, "SHA256SUMS.sig"),
            (archive, "release archive"),
            (manifest, "payload manifest"),
        ):
            _safe_regular_file(
                path,
                label,
            )

        verified, fingerprint, verify_reason = (
            signature_verifier(
                signature,
                sums,
                trust_anchor,
            )
        )

        if not verified:
            raise BootstrapPlanError(
                verify_reason
                or "release signature verification failed"
            )

        if fingerprint != EXPECTED_FINGERPRINT:
            raise BootstrapPlanError(
                "release signer fingerprint drift"
            )

        sums_entries = _parse_sha256sums(
            sums
        )

        if set(sums_entries) != {
            archive_name,
            manifest_name,
        }:
            raise BootstrapPlanError(
                "SHA256SUMS release artifact set mismatch"
            )

        archive_sha = _sha256_file(
            archive
        )

        manifest_sha = _sha256_file(
            manifest
        )

        if sums_entries[archive_name] != archive_sha:
            raise BootstrapPlanError(
                "release archive SHA-256 mismatch"
            )

        if sums_entries[manifest_name] != manifest_sha:
            raise BootstrapPlanError(
                "payload manifest SHA-256 mismatch"
            )

        payload_entries = _parse_payload_manifest(
            manifest
        )

        source_hashes: dict[str, str] = {}

        for relative in REQUIRED_PAYLOAD_SOURCES:
            expected = payload_entries.get(
                relative
            )

            if expected is None:
                raise BootstrapPlanError(
                    f"signed payload source missing: {relative}"
                )

            source = project_root / relative

            _safe_regular_file(
                source,
                f"signed payload source {relative}",
            )

            actual = _sha256_file(
                source
            )

            if actual != expected:
                raise BootstrapPlanError(
                    f"signed payload source drift: {relative}"
                )

            source_hashes[relative] = actual

        release_state_target = (
            release_base / release
        )

        release_state_hashes = {
            "SHA256SUMS": _sha256_file(
                sums
            ),
            "SHA256SUMS.sig": _sha256_file(
                signature
            ),
            manifest_name: manifest_sha,
        }

        release_state_state = (
            _release_state_target_state(
                release_state_target,
                release_state_hashes,
            )
        )

        bootstrap_state = _file_target_state(
            bootstrap_target,
            source_hashes[
                "tools/"
                "memoria_release_runtime_integrity.py"
            ],
            0o644,
        )

        launcher_state = _file_target_state(
            launcher_target,
            source_hashes[
                "tools/memoria_runtime_launcher.py"
            ],
            0o755,
        )

        identity_state = _identity_target_state(
            identity_target
        )

        result.update(
            {
                "bundle_context_sha256":
                    _canonical_sha256(
                        bundle_context
                    ),
                "active_release": release,
                "project_root":
                    str(project_root),
                "bundle_dir":
                    str(bundle_dir),
                "signer_fingerprint":
                    fingerprint,
                "release_state_target":
                    str(release_state_target),
                "release_state_target_state":
                    release_state_state,
                "bootstrap_target":
                    str(bootstrap_target),
                "bootstrap_target_state":
                    bootstrap_state,
                "launcher_target":
                    str(launcher_target),
                "launcher_target_state":
                    launcher_state,
                "identity_target":
                    str(identity_target),
                "identity_target_state":
                    identity_state,
                "source_hashes":
                    source_hashes,
                "release_state_hashes":
                    release_state_hashes,
            }
        )

        acceptable_stage_states = {
            "ABSENT",
            "ALREADY STAGED",
        }

        if (
            release_state_state
            not in acceptable_stage_states
        ):
            raise BootstrapPlanError(
                "release-state target is not safe "
                "for fresh bootstrap"
            )

        if (
            bootstrap_state
            not in acceptable_stage_states
        ):
            raise BootstrapPlanError(
                "bootstrap verifier target is not safe "
                "for fresh bootstrap"
            )

        if (
            launcher_state
            not in acceptable_stage_states
        ):
            raise BootstrapPlanError(
                "launcher target is not safe "
                "for fresh bootstrap"
            )

        if identity_state != "ABSENT":
            raise BootstrapPlanError(
                "installed runtime identity must be absent "
                "for fresh bootstrap"
            )

        result["plan_status"] = (
            "READY FOR APPROVAL"
        )

        result["approvable"] = True
        result["reason"] = (
            "Signed external release bundle and "
            "fresh-bootstrap targets verified."
        )

    except Exception as exc:
        result["plan_status"] = "BLOCKED"
        result["approvable"] = False
        result["reason"] = (
            f"{type(exc).__name__}: {exc}"
        )

    result["plan_sha256"] = _plan_sha256(
        result
    )

    return result


def build_runtime_bootstrap_plan(
    bundle_context: dict[str, Any],
) -> dict[str, Any]:
    """
    Public production entry.

    Source bundle/project paths come from the explicitly
    supplied release-bundle context.

    System trust and installation targets are fixed and
    cannot be overridden through this public entry.
    """

    return _build_runtime_bootstrap_plan_with_paths(
        bundle_context,
        trust_anchor=CANONICAL_TRUST_ANCHOR,
        release_base=CANONICAL_RELEASE_BASE,
        bootstrap_target=CANONICAL_BOOTSTRAP_TARGET,
        launcher_target=CANONICAL_LAUNCHER_TARGET,
        identity_target=CANONICAL_IDENTITY_TARGET,
        signature_verifier=(
            _default_signature_verifier
        ),
    )
