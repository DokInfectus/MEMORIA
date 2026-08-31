#!/usr/bin/env python3
from __future__ import annotations

import ctypes
import errno
import fcntl
import hashlib
import os
import stat
from pathlib import Path
from typing import Any

from memoria_trust_anchor_rebootstrap_approval import (
    rebootstrap_plan_is_approvable,
)
from memoria_trust_anchor_rebootstrap_authorization import (
    TrustAnchorRebootstrapAuthorizationStore,
)
from memoria_trust_anchor_rebootstrap_plan import (
    DEFAULT_SOURCE,
    DEFAULT_TARGET,
    EXPECTED_CURRENT_SHA256,
    EXPECTED_REPLACEMENT_SHA256,
    build_trust_anchor_rebootstrap_plan,
)


SCHEMA_VERSION = (
    "memoria-trust-anchor-rebootstrap-runner-v0.1"
)

RENAME_EXCHANGE = 2
TARGET_MODE = 0o644
LOCK_MODE = 0o600
MAX_TRUST_ANCHOR_BYTES = 1024 * 1024

_DIRECTORY_FLAGS = (
    os.O_RDONLY
    | os.O_DIRECTORY
    | os.O_NOFOLLOW
    | os.O_CLOEXEC
)

_LOCK_PAYLOAD = (
    b"memoria-trust-anchor-rebootstrap-v0.1\n"
)
_LOCK_PAYLOAD_SHA256 = hashlib.sha256(
    _LOCK_PAYLOAD
).hexdigest()

_LIBC = ctypes.CDLL(None, use_errno=True)

if not hasattr(_LIBC, "renameat2"):
    raise RuntimeError("libc renameat2 unavailable")

_RENAMEAT2 = _LIBC.renameat2
_RENAMEAT2.argtypes = (
    ctypes.c_int,
    ctypes.c_char_p,
    ctypes.c_int,
    ctypes.c_char_p,
    ctypes.c_uint,
)
_RENAMEAT2.restype = ctypes.c_int


def _simple_name(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
        or "\x00" in value
    ):
        raise ValueError("unsafe single path component")

    return value


def _names(target_name: str) -> tuple[str, str, str]:
    target_name = _simple_name(target_name)

    return (
        f".{target_name}.rebootstrap.lock",
        f".{target_name}.rebootstrap.guard",
        f".{target_name}.rebootstrap.pending",
    )


def _verify_directory_fd(fd: int) -> None:
    meta = os.fstat(fd)

    if not stat.S_ISDIR(meta.st_mode):
        raise ValueError("target parent is not directory")

    if meta.st_uid != 0 or meta.st_gid != 0:
        raise ValueError("target parent is not root:root")

    if stat.S_IMODE(meta.st_mode) & 0o022:
        raise ValueError(
            "target parent is group/world writable"
        )


def _open_verified_absolute_directory(
    directory: Path,
) -> int:
    directory = Path(directory)

    if not directory.is_absolute():
        raise ValueError(
            "target directory must be absolute"
        )

    current_fd = os.open(
        "/",
        _DIRECTORY_FLAGS,
    )

    try:
        _verify_directory_fd(current_fd)

        for part in directory.parts[1:]:
            part = _simple_name(part)

            next_fd = os.open(
                part,
                _DIRECTORY_FLAGS,
                dir_fd=current_fd,
            )

            try:
                _verify_directory_fd(next_fd)
            except Exception:
                os.close(next_fd)
                raise

            os.close(current_fd)
            current_fd = next_fd

        return current_fd

    except Exception:
        os.close(current_fd)
        raise


def _read_verified_source(
    source: Path,
    expected_sha256: str,
) -> bytes:
    source = Path(source)

    fd = os.open(
        source,
        os.O_RDONLY
        | os.O_NOFOLLOW
        | os.O_CLOEXEC,
    )

    try:
        meta = os.fstat(fd)

        if not stat.S_ISREG(meta.st_mode):
            raise ValueError(
                "replacement source is not regular"
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
                    "replacement source exceeds size limit"
                )

            digest.update(chunk)
            chunks.append(chunk)

    finally:
        os.close(fd)

    if digest.hexdigest() != expected_sha256:
        raise ValueError(
            "replacement source SHA-256 drift"
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
            raise OSError("short write")

        offset += written


def _create_lock_at(
    parent_fd: int,
    lock_name: str,
) -> None:
    lock_name = _simple_name(lock_name)

    fd = os.open(
        lock_name,
        (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | os.O_NOFOLLOW
            | os.O_CLOEXEC
        ),
        LOCK_MODE,
        dir_fd=parent_fd,
    )

    try:
        _write_all(fd, _LOCK_PAYLOAD)

        os.fchown(fd, 0, 0)
        os.fchmod(fd, LOCK_MODE)
        os.fsync(fd)

    finally:
        os.close(fd)

    lock_sha, _ = _hash_regular_at(
        parent_fd,
        lock_name,
        mode=LOCK_MODE,
    )

    if lock_sha != _LOCK_PAYLOAD_SHA256:
        raise ValueError(
            "created transaction lock verification failed"
        )

    os.fsync(parent_fd)


def _create_guard_at(
    parent_fd: int,
    target_name: str,
    guard_name: str,
    expected_old_sha256: str,
) -> tuple[int, int]:
    target_name = _simple_name(target_name)
    guard_name = _simple_name(guard_name)

    target_sha, target_inode = _hash_regular_at(
        parent_fd,
        target_name,
        mode=TARGET_MODE,
    )

    if target_sha != expected_old_sha256:
        raise ValueError(
            "target drift before guard creation"
        )

    os.link(
        target_name,
        guard_name,
        src_dir_fd=parent_fd,
        dst_dir_fd=parent_fd,
        follow_symlinks=False,
    )

    os.fsync(parent_fd)

    guard_sha, guard_inode = _hash_regular_at(
        parent_fd,
        guard_name,
        mode=TARGET_MODE,
    )

    if (
        guard_sha != expected_old_sha256
        or guard_inode != target_inode
    ):
        raise ValueError(
            "guard does not bind verified target inode"
        )

    return guard_inode


def _create_pending_at(
    parent_fd: int,
    pending_name: str,
    payload: bytes,
    expected_new_sha256: str,
) -> tuple[int, int]:
    pending_name = _simple_name(pending_name)

    fd = os.open(
        pending_name,
        (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | os.O_NOFOLLOW
            | os.O_CLOEXEC
        ),
        0o600,
        dir_fd=parent_fd,
    )

    try:
        _write_all(fd, payload)

        os.fchown(fd, 0, 0)
        os.fchmod(fd, TARGET_MODE)
        os.fsync(fd)

    finally:
        os.close(fd)

    pending_sha, pending_inode = _hash_regular_at(
        parent_fd,
        pending_name,
        mode=TARGET_MODE,
    )

    if pending_sha != expected_new_sha256:
        raise ValueError(
            "pending replacement SHA-256 mismatch"
        )

    os.fsync(parent_fd)

    return pending_inode


def _hash_regular_at(
    parent_fd: int,
    name: str,
    *,
    mode: int,
) -> tuple[str, tuple[int, int]]:
    name = _simple_name(name)

    fd = os.open(
        name,
        os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
        dir_fd=parent_fd,
    )

    try:
        meta = os.fstat(fd)

        if not stat.S_ISREG(meta.st_mode):
            raise ValueError(f"{name}: not regular")

        if meta.st_uid != 0 or meta.st_gid != 0:
            raise ValueError(f"{name}: not root:root")

        if stat.S_IMODE(meta.st_mode) != mode:
            raise ValueError(f"{name}: mode mismatch")

        digest = hashlib.sha256()

        while True:
            chunk = os.read(fd, 64 * 1024)

            if not chunk:
                break

            digest.update(chunk)

        return (
            digest.hexdigest(),
            (meta.st_dev, meta.st_ino),
        )

    finally:
        os.close(fd)


def _exchange_at(
    parent_fd: int,
    first: str,
    second: str,
) -> None:
    first = _simple_name(first)
    second = _simple_name(second)

    ctypes.set_errno(0)

    result = _RENAMEAT2(
        parent_fd,
        os.fsencode(first),
        parent_fd,
        os.fsencode(second),
        RENAME_EXCHANGE,
    )

    if result != 0:
        number = ctypes.get_errno()

        raise OSError(
            number,
            os.strerror(number),
        )

    os.fsync(parent_fd)


def _unlink_if_exists(
    parent_fd: int,
    name: str,
) -> None:
    try:
        os.unlink(
            _simple_name(name),
            dir_fd=parent_fd,
        )
    except FileNotFoundError:
        return


def _acquire_directory_transaction_lock(
    parent_fd: int,
) -> None:
    try:
        fcntl.flock(
            parent_fd,
            fcntl.LOCK_EX | fcntl.LOCK_NB,
        )
    except BlockingIOError as exc:
        raise RuntimeError(
            "another rebootstrap transaction is active"
        ) from exc


def _release_directory_transaction_lock(
    parent_fd: int,
) -> None:
    fcntl.flock(
        parent_fd,
        fcntl.LOCK_UN,
    )


def _recover_transaction_at_locked(
    parent_fd: int,
    target_name: str,
    *,
    expected_old_sha256: str,
    expected_new_sha256: str,
) -> str:
    """
    Explicit recovery of one interrupted rebootstrap.

    This function never discovers arbitrary files.
    It inspects only the three fixed transaction names.
    """

    _verify_directory_fd(parent_fd)

    target_name = _simple_name(target_name)

    lock_name, guard_name, pending_name = (
        _names(target_name)
    )

    entries = set(os.listdir(parent_fd))

    present = {
        name
        for name in (
            lock_name,
            guard_name,
            pending_name,
        )
        if name in entries
    }

    if not present:
        return "NO TRANSACTION"

    if lock_name not in present:
        raise ValueError(
            "transaction artifacts exist without lock"
        )

    lock_sha, _ = _hash_regular_at(
        parent_fd,
        lock_name,
        mode=LOCK_MODE,
    )

    if lock_sha != _LOCK_PAYLOAD_SHA256:
        raise ValueError(
            "transaction lock payload drift"
        )

    target_sha, target_inode = _hash_regular_at(
        parent_fd,
        target_name,
        mode=TARGET_MODE,
    )

    guard_exists = guard_name in present
    pending_exists = pending_name in present

    guard_sha = None
    guard_inode = None
    pending_sha = None
    pending_inode = None

    if guard_exists:
        guard_sha, guard_inode = _hash_regular_at(
            parent_fd,
            guard_name,
            mode=TARGET_MODE,
        )

        if guard_sha != expected_old_sha256:
            raise ValueError("guard hash drift")

    if pending_exists:
        pending_sha, pending_inode = _hash_regular_at(
            parent_fd,
            pending_name,
            mode=TARGET_MODE,
        )

    # Lock-only state can mean:
    #
    # - crash immediately after lock creation
    # - crash during successful commit cleanup
    # - crash during rollback/abort cleanup
    #
    # With no guard or pending left, preserve the current
    # verified regular target and remove only our lock.
    if not guard_exists and not pending_exists:
        _unlink_if_exists(parent_fd, lock_name)
        os.fsync(parent_fd)

        if target_sha == expected_old_sha256:
            return "ABORTED BEFORE GUARD"

        if target_sha == expected_new_sha256:
            return "COMMIT CLEANUP RECOVERED"

        return "ABORTED WITH TARGET DRIFT"

    # Guard without pending can mean:
    #
    # - crash before pending creation
    # - crash after a valid commit while pending cleanup
    #   already completed
    # - pre-exchange target drift
    if guard_exists and not pending_exists:
        if (
            target_sha == expected_old_sha256
            and target_inode == guard_inode
        ):
            _unlink_if_exists(parent_fd, guard_name)
            _unlink_if_exists(parent_fd, lock_name)
            os.fsync(parent_fd)

            return "ABORTED BEFORE PENDING"

        if target_sha == expected_new_sha256:
            _unlink_if_exists(parent_fd, guard_name)
            _unlink_if_exists(parent_fd, lock_name)
            os.fsync(parent_fd)

            return "COMMIT CLEANUP RECOVERED"

        # Preserve an externally changed target.
        _unlink_if_exists(parent_fd, guard_name)
        _unlink_if_exists(parent_fd, lock_name)
        os.fsync(parent_fd)

        return "ABORTED WITH TARGET DRIFT"

    if not guard_exists and pending_exists:
        raise ValueError(
            "pending exists without guard"
        )

    # Pre-exchange state.
    if (
        target_sha == expected_old_sha256
        and target_inode == guard_inode
        and pending_sha == expected_new_sha256
    ):
        _unlink_if_exists(parent_fd, pending_name)
        _unlink_if_exists(parent_fd, guard_name)
        _unlink_if_exists(parent_fd, lock_name)
        os.fsync(parent_fd)

        return "ABORTED BEFORE EXCHANGE"

    # Valid exchange completed before crash.
    if (
        target_sha == expected_new_sha256
        and pending_sha == expected_old_sha256
        and pending_inode == guard_inode
    ):
        _unlink_if_exists(parent_fd, pending_name)
        _unlink_if_exists(parent_fd, guard_name)
        _unlink_if_exists(parent_fd, lock_name)
        os.fsync(parent_fd)

        return "COMMIT RECOVERED"

    # Exchange happened after target race.
    if (
        target_sha == expected_new_sha256
        and pending_inode != guard_inode
    ):
        _exchange_at(
            parent_fd,
            target_name,
            pending_name,
        )

        # The new candidate must have returned to pending.
        restored_pending_sha, _ = _hash_regular_at(
            parent_fd,
            pending_name,
            mode=TARGET_MODE,
        )

        if restored_pending_sha != expected_new_sha256:
            raise ValueError(
                "rollback did not restore pending candidate"
            )

        _unlink_if_exists(parent_fd, pending_name)
        _unlink_if_exists(parent_fd, guard_name)
        _unlink_if_exists(parent_fd, lock_name)
        os.fsync(parent_fd)

        return "RACED EXCHANGE ROLLED BACK"

    # External target drift before exchange.
    if (
        target_sha != expected_new_sha256
        and pending_sha == expected_new_sha256
        and guard_sha == expected_old_sha256
    ):
        _unlink_if_exists(parent_fd, pending_name)
        _unlink_if_exists(parent_fd, guard_name)
        _unlink_if_exists(parent_fd, lock_name)
        os.fsync(parent_fd)

        return "ABORTED WITH TARGET DRIFT"

    raise ValueError(
        "ambiguous rebootstrap recovery state"
    )


def recover_transaction_at(
    parent_fd: int,
    target_name: str,
    *,
    expected_old_sha256: str,
    expected_new_sha256: str,
) -> str:
    """
    Recover only when no live MEMORIA rebootstrap runner
    owns the verified target directory transaction lock.
    """

    _acquire_directory_transaction_lock(parent_fd)

    try:
        return _recover_transaction_at_locked(
            parent_fd,
            target_name,
            expected_old_sha256=expected_old_sha256,
            expected_new_sha256=expected_new_sha256,
        )

    finally:
        _release_directory_transaction_lock(parent_fd)


def run_trust_anchor_rebootstrap_attempt(
    authorization: dict[str, Any],
    authorization_store: (
        TrustAnchorRebootstrapAuthorizationStore
    ),
    *,
    source: Path = DEFAULT_SOURCE,
    target: Path = DEFAULT_TARGET,
    expected_current_sha256: str = (
        EXPECTED_CURRENT_SHA256
    ),
    expected_replacement_sha256: str = (
        EXPECTED_REPLACEMENT_SHA256
    ),
) -> tuple[int, dict[str, Any]]:
    """
    Execute one explicitly authorized Trust Anchor
    rebootstrap attempt.

    The directory transaction flock is held continuously
    across recovery, authorization consumption and commit.

    No authorization is persisted.
    No retry occurs after one-shot consumption.
    """

    source = Path(source)
    target = Path(target)

    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "runner_status": "BLOCKED",
        "reason": None,
        "plan_sha256": None,
        "post_consume_plan_sha256": None,
        "authorization_consumed": False,
        "exchange_performed": False,
        "execution_performed": False,
        "recovery_state": None,
    }

    if not target.is_absolute():
        result["reason"] = (
            "Trust Anchor target must be absolute."
        )
        return 2, result

    try:
        target_name = _simple_name(target.name)
    except ValueError as exc:
        result["reason"] = str(exc)
        return 2, result

    parent_fd: int | None = None
    directory_lock_held = False
    transaction_started = False

    try:
        parent_fd = _open_verified_absolute_directory(
            target.parent
        )

        _acquire_directory_transaction_lock(
            parent_fd
        )
        directory_lock_held = True

        # First settle any transaction left by a crashed
        # prior invocation while we own the kernel lock.
        recovery_state = (
            _recover_transaction_at_locked(
                parent_fd,
                target_name,
                expected_old_sha256=(
                    expected_current_sha256
                ),
                expected_new_sha256=(
                    expected_replacement_sha256
                ),
            )
        )

        result["recovery_state"] = recovery_state

        current_plan = (
            build_trust_anchor_rebootstrap_plan(
                source=source,
                target=target,
                expected_current_sha256=(
                    expected_current_sha256
                ),
                expected_replacement_sha256=(
                    expected_replacement_sha256
                ),
            )
        )

        result["plan_sha256"] = current_plan.get(
            "plan_sha256"
        )

        # A previous authorized invocation may have
        # completed the exchange and crashed only during
        # cleanup. Recovery of that state must not consume
        # a second authorization.
        if recovery_state in {
            "COMMIT RECOVERED",
            "COMMIT CLEANUP RECOVERED",
        }:
            if (
                current_plan.get("plan_status")
                != "ALREADY REBOOTSTRAPPED"
                or current_plan.get("target_state")
                != "ALREADY REBOOTSTRAPPED"
            ):
                result["reason"] = (
                    "Recovered commit does not match "
                    "final Trust Anchor state."
                )
                return 3, result

            result["runner_status"] = (
                "PRIOR COMMIT RECOVERED"
            )
            result["reason"] = (
                "Interrupted prior rebootstrap commit "
                "was recovered without consuming the "
                "presented authorization."
            )

            return 0, result

        # Build/inspect the exact current plan before
        # consuming the one-shot authorization.
        allowed, consumed_record = (
            authorization_store.verify_and_consume(
                authorization,
                current_plan,
            )
        )

        if not allowed:
            result["reason"] = consumed_record.get(
                "reason"
            )
            return 4, result

        result["authorization_consumed"] = True

        # One-shot has now been consumed. Every subsequent
        # failure is BLOCKED AFTER CONSUME and may never
        # reuse this authorization.
        post_consume_plan = (
            build_trust_anchor_rebootstrap_plan(
                source=source,
                target=target,
                expected_current_sha256=(
                    expected_current_sha256
                ),
                expected_replacement_sha256=(
                    expected_replacement_sha256
                ),
            )
        )

        result["post_consume_plan_sha256"] = (
            post_consume_plan.get("plan_sha256")
        )

        if (
            not rebootstrap_plan_is_approvable(
                post_consume_plan
            )
            or post_consume_plan.get("plan_sha256")
            != current_plan.get("plan_sha256")
        ):
            result["runner_status"] = (
                "BLOCKED AFTER CONSUME"
            )
            result["reason"] = (
                "Trust Anchor plan drifted after "
                "one-shot authorization consumption."
            )

            return 5, result

        # Re-read the exact replacement bytes after
        # authorization consumption.
        payload = _read_verified_source(
            source,
            expected_replacement_sha256,
        )

        lock_name, guard_name, pending_name = (
            _names(target_name)
        )

        _create_lock_at(
            parent_fd,
            lock_name,
        )
        transaction_started = True

        expected_guard_inode = _create_guard_at(
            parent_fd,
            target_name,
            guard_name,
            expected_current_sha256,
        )

        _create_pending_at(
            parent_fd,
            pending_name,
            payload,
            expected_replacement_sha256,
        )

        # Final pre-exchange compare against the exact
        # guarded old inode.
        target_sha, target_inode = _hash_regular_at(
            parent_fd,
            target_name,
            mode=TARGET_MODE,
        )

        guard_sha, guard_inode = _hash_regular_at(
            parent_fd,
            guard_name,
            mode=TARGET_MODE,
        )

        pending_sha, _ = _hash_regular_at(
            parent_fd,
            pending_name,
            mode=TARGET_MODE,
        )

        if (
            target_sha != expected_current_sha256
            or guard_sha != expected_current_sha256
            or pending_sha
            != expected_replacement_sha256
            or target_inode != guard_inode
            or guard_inode != expected_guard_inode
        ):
            cleanup_state = (
                _recover_transaction_at_locked(
                    parent_fd,
                    target_name,
                    expected_old_sha256=(
                        expected_current_sha256
                    ),
                    expected_new_sha256=(
                        expected_replacement_sha256
                    ),
                )
            )

            transaction_started = False
            result["recovery_state"] = cleanup_state
            result["runner_status"] = (
                "BLOCKED AFTER CONSUME"
            )
            result["reason"] = (
                "Final pre-exchange Trust Anchor "
                "identity check failed."
            )

            return 6, result

        # Atomic same-directory exchange.
        _exchange_at(
            parent_fd,
            pending_name,
            target_name,
        )

        result["exchange_performed"] = True

        # The same already-tested state machine decides
        # whether this was a legitimate commit or a raced
        # exchange requiring rollback.
        commit_state = (
            _recover_transaction_at_locked(
                parent_fd,
                target_name,
                expected_old_sha256=(
                    expected_current_sha256
                ),
                expected_new_sha256=(
                    expected_replacement_sha256
                ),
            )
        )

        transaction_started = False
        result["recovery_state"] = commit_state

        if commit_state != "COMMIT RECOVERED":
            result["runner_status"] = (
                "BLOCKED AFTER CONSUME"
            )
            result["reason"] = (
                "Atomic exchange did not resolve "
                "to a valid committed Trust Anchor."
            )

            return 7, result

        final_sha, _ = _hash_regular_at(
            parent_fd,
            target_name,
            mode=TARGET_MODE,
        )

        if final_sha != expected_replacement_sha256:
            result["runner_status"] = (
                "BLOCKED AFTER CONSUME"
            )
            result["reason"] = (
                "Final installed Trust Anchor "
                "verification failed."
            )

            return 8, result

        result["execution_performed"] = True
        result["runner_status"] = (
            "TRUST ANCHOR REBOOTSTRAP COMPLETE"
        )
        result["reason"] = (
            "Explicit one-shot Trust Anchor "
            "rebootstrap completed and verified."
        )

        return 0, result

    except Exception as exc:
        # After consumption there is never a retry.
        #
        # If transaction artifacts were already created,
        # make one deterministic recovery attempt while
        # still holding the directory flock. Ambiguous
        # state remains fail-closed for explicit admin
        # inspection.
        if (
            parent_fd is not None
            and directory_lock_held
            and transaction_started
        ):
            try:
                cleanup_state = (
                    _recover_transaction_at_locked(
                        parent_fd,
                        target_name,
                        expected_old_sha256=(
                            expected_current_sha256
                        ),
                        expected_new_sha256=(
                            expected_replacement_sha256
                        ),
                    )
                )

                result["recovery_state"] = (
                    cleanup_state
                )
                transaction_started = False

            except Exception as recovery_exc:
                result["recovery_state"] = (
                    "AMBIGUOUS - EXPLICIT ADMIN "
                    f"RECOVERY REQUIRED: {recovery_exc}"
                )

        if result["authorization_consumed"]:
            result["runner_status"] = (
                "BLOCKED AFTER CONSUME"
            )
        else:
            result["runner_status"] = "BLOCKED"

        result["reason"] = str(exc)

        return 9, result

    finally:
        if (
            parent_fd is not None
            and directory_lock_held
        ):
            _release_directory_transaction_lock(
                parent_fd
            )

        if parent_fd is not None:
            os.close(parent_fd)
