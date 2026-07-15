"""Owned publication lock with explicit, conservative stale recovery."""
from __future__ import annotations

import datetime as dt
import json
import os
import socket
import uuid
from contextlib import contextmanager
from pathlib import Path

from .provenance import canonical_bytes
from .validation import ContractError


REQUIRED = {"token", "pid", "host", "created_at", "operation_id"}


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def validate_metadata(value: object) -> dict:
    if not isinstance(value, dict) or set(value) != REQUIRED:
        raise ContractError("publication lock metadata is malformed")
    if not isinstance(value["token"], str) or len(value["token"]) != 32:
        raise ContractError("publication lock token is malformed")
    if not isinstance(value["pid"], int) or value["pid"] <= 0:
        raise ContractError("publication lock pid is malformed")
    if not isinstance(value["host"], str) or not value["host"]:
        raise ContractError("publication lock host is malformed")
    if not isinstance(value["operation_id"], str) or not value["operation_id"]:
        raise ContractError("publication lock operation_id is malformed")
    try:
        created = dt.datetime.fromisoformat(value["created_at"].replace("Z", "+00:00"))
        if created.tzinfo is None:
            raise ValueError
    except (AttributeError, ValueError) as error:
        raise ContractError("publication lock created_at is malformed") from error
    return value


def read_lock(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ContractError("publication lock is unreadable or malformed; use explicit recovery") from error
    return validate_metadata(value)


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def acquire(path: Path, operation_id: str) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    metadata = {
        "token": uuid.uuid4().hex, "pid": os.getpid(), "host": socket.gethostname(),
        "created_at": _now().isoformat().replace("+00:00", "Z"), "operation_id": operation_id,
    }
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as error:
        raise ContractError("another publication is in progress") from error
    try:
        os.write(descriptor, canonical_bytes(metadata))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return metadata


def release(path: Path, token: str) -> None:
    if not path.exists():
        return
    metadata = read_lock(path)
    if metadata["token"] != token:
        raise ContractError("publication lock token mismatch; lock not released")
    path.unlink()


def inspect(path: Path, *, now: dt.datetime | None = None, stale_after: dt.timedelta = dt.timedelta(hours=6)) -> dict:
    metadata = read_lock(path)
    current = now or _now()
    created = dt.datetime.fromisoformat(metadata["created_at"].replace("Z", "+00:00"))
    same_host = metadata["host"] == socket.gethostname()
    live = same_host and pid_alive(metadata["pid"])
    return {**metadata, "age_seconds": (current - created).total_seconds(), "same_host_live_pid": live,
            "stale_candidate": current - created >= stale_after and not live}


def recover(path: Path, *, stale_after: dt.timedelta, now: dt.datetime | None = None) -> bool:
    status = inspect(path, now=now, stale_after=stale_after)
    if not status["stale_candidate"]:
        raise ContractError("publication lock is not safely recoverable")
    # Re-read immediately before unlinking so a replaced lock cannot be removed.
    current = read_lock(path)
    if current["token"] != status["token"]:
        raise ContractError("publication lock changed during recovery")
    path.unlink()
    return True


@contextmanager
def owned_lock(path: Path, operation_id: str):
    metadata = acquire(path, operation_id)
    try:
        yield metadata
    finally:
        release(path, metadata["token"])
