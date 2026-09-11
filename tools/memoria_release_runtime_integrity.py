#!/usr/bin/env python3

import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path


GPGV = Path("/usr/bin/gpgv")

EXPECTED_FINGERPRINT = (
    "2A43DDB1EB6CAE0E011D8C688F3BBFD776DF59A3"
)

RELEASE_SIGNER_FINGERPRINTS = {
    "0.1.9-beta": (
        "E27B877C3B5AB6C74C33399C9E82CC6E190E5E85"
    ),
    "0.2.0-beta": EXPECTED_FINGERPRINT,
    "0.2.1": EXPECTED_FINGERPRINT,
}

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_STATE_FILE = 16 * 1024 * 1024
IDENTITY_MAX_BYTES = 64 * 1024

IDENTITY_SCHEMA = "memoria-installed-runtime-v0.1"

CANONICAL_IDENTITY = Path(
    "/var/local/memoria/installed-runtime.json"
)

CANONICAL_RELEASE_BASE = Path(
    "/usr/local/share/memoria/release"
)

CANONICAL_KEYRING = Path(
    "/usr/share/keyrings/memoria-release.gpg"
)

IDENTITY_KEYS = {
    "schema_version",
    "project_root",
    "active_release",
}

RELEASE_RE = re.compile(
    r"^[0-9]+\.[0-9]+\.[0-9]+"
    r"(?:-beta)?$"
)


class IntegrityError(RuntimeError):
    pass


def verify_metadata(meta, label, *, directory=False):
    if directory:
        if not stat.S_ISDIR(meta.st_mode):
            raise IntegrityError(
                f"{label}: directory required"
            )
    else:
        if not stat.S_ISREG(meta.st_mode):
            raise IntegrityError(
                f"{label}: regular file required"
            )

    if meta.st_uid != 0 or meta.st_gid != 0:
        raise IntegrityError(
            f"{label}: root:root required"
        )

    if meta.st_mode & 0o022:
        raise IntegrityError(
            f"{label}: group/world writable"
        )




def open_absolute_directory_chain_no_symlinks(path):
    path = Path(path)

    if not path.is_absolute():
        raise IntegrityError(
            "project_root must be absolute"
        )

    if ".." in path.parts:
        raise IntegrityError(
            "project_root contains unsafe component"
        )

    current_fd = os.open(
        "/",
        os.O_RDONLY
        | os.O_DIRECTORY
        | os.O_NOFOLLOW
        | os.O_CLOEXEC,
    )

    try:
        if not stat.S_ISDIR(
            os.fstat(current_fd).st_mode
        ):
            raise IntegrityError(
                "filesystem root is not directory"
            )

        for part in path.parts[1:]:
            next_fd = os.open(
                part,
                os.O_RDONLY
                | os.O_DIRECTORY
                | os.O_NOFOLLOW
                | os.O_CLOEXEC,
                dir_fd=current_fd,
            )

            try:
                meta = os.fstat(next_fd)

                if not stat.S_ISDIR(meta.st_mode):
                    raise IntegrityError(
                        f"project_root component "
                        f"is not directory: {part}"
                    )

            except Exception:
                os.close(next_fd)
                raise

            os.close(current_fd)
            current_fd = next_fd

        return current_fd

    except Exception:
        try:
            os.close(current_fd)
        except OSError:
            pass
        raise

def open_verified_absolute_directory_chain(path):
    path = Path(path)

    if not path.is_absolute():
        raise IntegrityError(
            "absolute directory path required"
        )

    current_fd = os.open(
        "/",
        os.O_RDONLY
        | os.O_DIRECTORY
        | os.O_NOFOLLOW
        | os.O_CLOEXEC,
    )

    try:
        verify_metadata(
            os.fstat(current_fd),
            "/",
            directory=True,
        )

        for part in path.parts[1:]:
            next_fd = os.open(
                part,
                os.O_RDONLY
                | os.O_DIRECTORY
                | os.O_NOFOLLOW
                | os.O_CLOEXEC,
                dir_fd=current_fd,
            )

            try:
                verify_metadata(
                    os.fstat(next_fd),
                    str(path),
                    directory=True,
                )
            except Exception:
                os.close(next_fd)
                raise

            os.close(current_fd)
            current_fd = next_fd

        return current_fd

    except Exception:
        try:
            os.close(current_fd)
        except OSError:
            pass
        raise

def open_verified_directory(path):
    fd = os.open(
        path,
        os.O_RDONLY
        | os.O_DIRECTORY
        | os.O_NOFOLLOW
        | os.O_CLOEXEC,
    )

    try:
        verify_metadata(
            os.fstat(fd),
            "release state directory",
            directory=True,
        )
    except Exception:
        os.close(fd)
        raise

    return fd


def open_verified_file_at(directory_fd, name):
    if (
        not name
        or name in {".", ".."}
        or "/" in name
        or "\x00" in name
    ):
        raise IntegrityError(
            f"unsafe state filename: {name!r}"
        )

    fd = os.open(
        name,
        os.O_RDONLY
        | os.O_NOFOLLOW
        | os.O_CLOEXEC,
        dir_fd=directory_fd,
    )

    try:
        verify_metadata(
            os.fstat(fd),
            name,
        )
    except Exception:
        os.close(fd)
        raise

    return fd


def open_verified_absolute_file(path, label):
    fd = os.open(
        path,
        os.O_RDONLY
        | os.O_NOFOLLOW
        | os.O_CLOEXEC,
    )

    try:
        verify_metadata(
            os.fstat(fd),
            label,
        )
    except Exception:
        os.close(fd)
        raise

    return fd


def read_fd(fd):
    before = os.fstat(fd)

    if before.st_size > MAX_STATE_FILE:
        raise IntegrityError(
            "release state file exceeds safety limit"
        )

    chunks = []
    offset = 0

    while offset < before.st_size:
        chunk = os.pread(
            fd,
            min(
                1024 * 1024,
                before.st_size - offset,
            ),
            offset,
        )

        if not chunk:
            raise IntegrityError(
                "unexpected short read"
            )

        chunks.append(chunk)
        offset += len(chunk)

    after = os.fstat(fd)

    if (
        before.st_dev != after.st_dev
        or before.st_ino != after.st_ino
        or before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or before.st_ctime_ns != after.st_ctime_ns
    ):
        raise IntegrityError(
            "release state file changed while being read"
        )

    return b"".join(chunks)


def verify_gpgv():
    meta = os.lstat(GPGV)

    verify_metadata(
        meta,
        "canonical gpgv",
    )

    if not meta.st_mode & stat.S_IXUSR:
        raise IntegrityError(
            "canonical gpgv not executable"
        )


def verify_signature(
    key_fd,
    sig_fd,
    sums_fd,
    expected_fingerprint=EXPECTED_FINGERPRINT,
):
    verify_gpgv()

    completed = subprocess.run(
        [
            str(GPGV),
            "--status-fd",
            "1",
            "--keyring",
            f"/proc/self/fd/{key_fd}",
            f"/proc/self/fd/{sig_fd}",
            f"/proc/self/fd/{sums_fd}",
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        pass_fds=(
            key_fd,
            sig_fd,
            sums_fd,
        ),
    )

    if completed.returncode != 0:
        raise IntegrityError(
            "gpgv rejected release signature"
        )

    fingerprints = []

    for line in completed.stdout.splitlines():
        fields = line.split()

        if (
            len(fields) >= 3
            and fields[0] == "[GNUPG:]"
            and fields[1] == "VALIDSIG"
        ):
            fingerprints.append(fields[2])

    if fingerprints != [expected_fingerprint]:
        raise IntegrityError(
            "release signer fingerprint mismatch"
        )

    return fingerprints[0]


def decode_utf8(data, label):
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise IntegrityError(
            f"{label}: invalid UTF-8"
        ) from exc


def expected_manifest_sha(sums_bytes, manifest_name):
    matches = []

    for line_no, raw in enumerate(
        decode_utf8(
            sums_bytes,
            "SHA256SUMS",
        ).splitlines(),
        start=1,
    ):
        if not raw:
            continue

        try:
            digest, name = raw.split("  ", 1)
        except ValueError:
            raise IntegrityError(
                f"SHA256SUMS malformed line {line_no}"
            )

        if not SHA256_RE.fullmatch(digest):
            raise IntegrityError(
                f"SHA256SUMS invalid digest line {line_no}"
            )

        if name == manifest_name:
            matches.append(digest)

    if len(matches) != 1:
        raise IntegrityError(
            "payload manifest must occur exactly once "
            "in SHA256SUMS"
        )

    return matches[0]


def parse_manifest(manifest_bytes):
    entries = []
    seen = set()

    for line_no, raw in enumerate(
        decode_utf8(
            manifest_bytes,
            "payload manifest",
        ).splitlines(),
        start=1,
    ):
        if not raw:
            continue

        try:
            digest, relative = raw.split("  ", 1)
        except ValueError:
            raise IntegrityError(
                f"manifest malformed line {line_no}"
            )

        if not SHA256_RE.fullmatch(digest):
            raise IntegrityError(
                f"manifest invalid digest line {line_no}"
            )

        if (
            not relative
            or relative.startswith("/")
            or relative.startswith("./")
            or "\x00" in relative
        ):
            raise IntegrityError(
                f"unsafe manifest path: {relative!r}"
            )

        parts = Path(relative).parts

        if ".." in parts:
            raise IntegrityError(
                f"unsafe manifest path: {relative!r}"
            )

        if relative in seen:
            raise IntegrityError(
                f"duplicate manifest path: {relative}"
            )

        seen.add(relative)
        entries.append(
            (digest, relative)
        )

    if not entries:
        raise IntegrityError(
            "payload manifest empty"
        )

    return entries


def hash_payload_file(root_fd, relative):
    parts = Path(relative).parts
    current_fd = os.dup(root_fd)

    try:
        for part in parts[:-1]:
            next_fd = os.open(
                part,
                os.O_RDONLY
                | os.O_DIRECTORY
                | os.O_NOFOLLOW
                | os.O_CLOEXEC,
                dir_fd=current_fd,
            )

            os.close(current_fd)
            current_fd = next_fd

        file_fd = os.open(
            parts[-1],
            os.O_RDONLY
            | os.O_NOFOLLOW
            | os.O_CLOEXEC,
            dir_fd=current_fd,
        )

        try:
            meta = os.fstat(file_fd)

            if not stat.S_ISREG(meta.st_mode):
                raise IntegrityError(
                    f"not regular file: {relative}"
                )

            digest = hashlib.sha256()

            while True:
                chunk = os.read(
                    file_fd,
                    1024 * 1024,
                )

                if not chunk:
                    break

                digest.update(chunk)

            return digest.hexdigest()

        finally:
            os.close(file_fd)

    finally:
        os.close(current_fd)


def verify(
    project_root,
    state_dir,
    manifest_name,
    keyring,
    expected_fingerprint=EXPECTED_FINGERPRINT,
):
    state_fd = None
    sums_fd = None
    sig_fd = None
    manifest_fd = None
    key_parent_fd = None
    key_fd = None
    root_fd = None

    try:
        state_fd = open_verified_absolute_directory_chain(
            state_dir
        )

        sums_fd = open_verified_file_at(
            state_fd,
            "SHA256SUMS",
        )

        sig_fd = open_verified_file_at(
            state_fd,
            "SHA256SUMS.sig",
        )

        manifest_fd = open_verified_file_at(
            state_fd,
            manifest_name,
        )

        key_parent_fd = (
            open_verified_absolute_directory_chain(
                keyring.parent
            )
        )

        key_fd = open_verified_file_at(
            key_parent_fd,
            keyring.name,
        )

        fingerprint = verify_signature(
            key_fd,
            sig_fd,
            sums_fd,
            expected_fingerprint,
        )

        sums_bytes = read_fd(sums_fd)
        manifest_bytes = read_fd(manifest_fd)

        expected_sha = expected_manifest_sha(
            sums_bytes,
            manifest_name,
        )

        actual_sha = hashlib.sha256(
            manifest_bytes
        ).hexdigest()

        if actual_sha != expected_sha:
            raise IntegrityError(
                "payload manifest SHA-256 mismatch"
            )

        entries = parse_manifest(
            manifest_bytes
        )

        root_fd = (
            open_absolute_directory_chain_no_symlinks(
                project_root
            )
        )

        match = 0
        drift = []
        missing = []
        unsafe = []

        for expected, relative in entries:
            try:
                current = hash_payload_file(
                    root_fd,
                    relative,
                )
            except FileNotFoundError:
                missing.append(relative)
                continue
            except (
                IntegrityError,
                OSError,
            ):
                unsafe.append(relative)
                continue

            if current == expected:
                match += 1
            else:
                drift.append(relative)

        return {
            "ok": not drift
            and not missing
            and not unsafe,
            "fingerprint": fingerprint,
            "manifest_sha256": actual_sha,
            "entries": len(entries),
            "match": match,
            "drift": drift,
            "missing": missing,
            "unsafe": unsafe,
        }

    finally:
        for fd in (
            root_fd,
            key_fd,
            key_parent_fd,
            manifest_fd,
            sig_fd,
            sums_fd,
            state_fd,
        ):
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass



def load_installed_runtime_identity(
    identity_path,
    release_base,
):
    identity_path = Path(identity_path)
    release_base = Path(release_base)

    if not identity_path.is_absolute():
        raise IntegrityError(
            "canonical identity path must be absolute"
        )

    if not release_base.is_absolute():
        raise IntegrityError(
            "release base must be absolute"
        )

    parent_fd = None
    identity_fd = None

    try:
        parent_fd = (
            open_verified_absolute_directory_chain(
                identity_path.parent
            )
        )

        identity_fd = open_verified_file_at(
            parent_fd,
            identity_path.name,
        )

        meta = os.fstat(identity_fd)

        if stat.S_IMODE(meta.st_mode) != 0o644:
            raise IntegrityError(
                "installed runtime identity mode must be 0644"
            )

        if meta.st_size > IDENTITY_MAX_BYTES:
            raise IntegrityError(
                "installed runtime identity exceeds size limit"
            )

        raw = read_fd(identity_fd)

    finally:
        for fd in (
            identity_fd,
            parent_fd,
        ):
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass

    try:
        identity = json.loads(
            decode_utf8(
                raw,
                "installed runtime identity",
            )
        )
    except json.JSONDecodeError as exc:
        raise IntegrityError(
            "installed runtime identity JSON invalid"
        ) from exc

    if not isinstance(identity, dict):
        raise IntegrityError(
            "installed runtime identity must be object"
        )

    if set(identity) != IDENTITY_KEYS:
        raise IntegrityError(
            "installed runtime identity keys are not exact"
        )

    if identity.get("schema_version") != IDENTITY_SCHEMA:
        raise IntegrityError(
            "installed runtime identity schema mismatch"
        )

    project_text = identity.get("project_root")

    if not isinstance(project_text, str):
        raise IntegrityError(
            "project_root must be string"
        )

    project_root = Path(project_text)

    if (
        not project_root.is_absolute()
        or ".." in project_root.parts
        or "\x00" in project_text
    ):
        raise IntegrityError(
            "project_root invalid"
        )

    active_release = identity.get(
        "active_release"
    )

    if (
        not isinstance(active_release, str)
        or not RELEASE_RE.fullmatch(
            active_release
        )
    ):
        raise IntegrityError(
            "active_release invalid"
        )

    return {
        "project_root": project_root,
        "active_release": active_release,
        "release_state": (
            release_base / active_release
        ),
        "manifest_name": (
            f"MEMORIA-{active_release}.payload.sha256"
        ),
    }


def _expected_fingerprint_for_release(
    active_release,
):
    fingerprint = RELEASE_SIGNER_FINGERPRINTS.get(
        active_release
    )

    if fingerprint is None:
        raise IntegrityError(
            "active release signer policy unavailable"
        )

    return fingerprint


def _verify_installed_runtime_with_paths(
    identity_path,
    release_base,
    keyring,
):
    identity = load_installed_runtime_identity(
        identity_path,
        release_base,
    )

    expected_fingerprint = (
        _expected_fingerprint_for_release(
            identity["active_release"]
        )
    )

    result = verify(
        identity["project_root"],
        identity["release_state"],
        identity["manifest_name"],
        Path(keyring),
        expected_fingerprint=expected_fingerprint,
    )

    result["project_root"] = str(
        identity["project_root"]
    )
    result["active_release"] = (
        identity["active_release"]
    )
    result["release_state"] = str(
        identity["release_state"]
    )
    result["manifest_name"] = (
        identity["manifest_name"]
    )

    return result


def verify_installed_runtime():
    return _verify_installed_runtime_with_paths(
        CANONICAL_IDENTITY,
        CANONICAL_RELEASE_BASE,
        CANONICAL_KEYRING,
    )


def main():
    if len(sys.argv) != 1:
        print("RUNTIME INTEGRITY: BLOCKED")
        print(
            "reason: production verifier accepts "
            "no path override arguments"
        )
        return 23

    try:
        result = verify_installed_runtime()

    except (
        IntegrityError,
        FileNotFoundError,
        OSError,
    ) as exc:
        print("RUNTIME INTEGRITY: BLOCKED")
        print(f"reason: {exc}")
        return 23

    print(
        "RUNTIME INTEGRITY: "
        + ("GREEN" if result["ok"] else "BLOCKED")
    )

    print(
        f"active_release: "
        f"{result['active_release']}"
    )
    print(
        f"project_root: "
        f"{result['project_root']}"
    )
    print(
        f"release_state: "
        f"{result['release_state']}"
    )
    print(
        f"fingerprint: "
        f"{result['fingerprint']}"
    )
    print(
        f"manifest_sha256: "
        f"{result['manifest_sha256']}"
    )
    print(f"entries: {result['entries']}")
    print(f"match: {result['match']}")
    print(f"drift: {len(result['drift'])}")
    print(f"missing: {len(result['missing'])}")
    print(f"unsafe: {len(result['unsafe'])}")

    for label in (
        "drift",
        "missing",
        "unsafe",
    ):
        for item in result[label][:20]:
            print(f"{label}: {item}")

    return 0 if result["ok"] else 23


if __name__ == "__main__":
    raise SystemExit(main())
