"""Advisory file locking for operational operations (C0.7/state)."""

from __future__ import annotations

import os
import time
from pathlib import Path


class LockError(Exception):
    """Could not acquire the requested lock."""


class LockTimeoutError(LockError):
    """The lock was not released within the timeout."""


class FileLock:
    """A simple, advisory O_EXCL-based lock.

    Not a substitute for OS-level locks on shared filesystems, but enough to
    serialize local migration/state writes between cooperating processes.
    """

    def __init__(self, lock_path: Path, timeout: float = 15.0, poll_interval: float = 0.1):
        self.lock_path = Path(lock_path)
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.acquired = False

    def acquire(self) -> None:
        lock_path = self.lock_path
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.write(fd, str(os.getpid()).encode("ascii"))
                os.close(fd)
                self.acquired = True
                return
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise LockTimeoutError(f"Timed out waiting for lock: {lock_path}")
                time.sleep(self.poll_interval)

    def release(self) -> None:
        if self.acquired:
            try:
                self.lock_path.unlink()
            except FileNotFoundError:
                pass
            self.acquired = False

    def __enter__(self) -> "FileLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()
