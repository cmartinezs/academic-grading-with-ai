"""Per-section/publication snapshot lock (P0 concurrency).

Wraps ``c0.locking.FileLock`` and adds stale-lock recovery: a lock whose owning
PID is no longer alive is broken and re-acquired. Every mutation of staging,
the manifest, the approvals and the destination runs under this lock.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from c0.locking import LockTimeoutError, FileLock


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class SnapshotLock:
    """Advisory lock keyed on (section_id, publication_id)."""

    def __init__(self, lock_path: Path, timeout: float = 60.0, poll_interval: float = 0.1):
        self.lock_path = Path(lock_path)
        self.timeout = timeout
        self.poll_interval = poll_interval
        self._lock = FileLock(self.lock_path, timeout=timeout, poll_interval=poll_interval)

    def _break_stale(self) -> bool:
        try:
            pid = int(self.lock_path.read_text(encoding="ascii").strip())
        except (OSError, ValueError):
            return False
        if not _pid_alive(pid):
            try:
                self.lock_path.unlink()
                return True
            except OSError:
                return False
        return False

    def acquire(self) -> None:
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                self._lock.acquire()
                return
            except LockTimeoutError:
                if self._break_stale():
                    continue
                raise
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise LockTimeoutError(f"Timed out waiting for lock: {self.lock_path}")
                if self._break_stale():
                    continue
                time.sleep(self.poll_interval)

    def release(self) -> None:
        self._lock.release()

    def __enter__(self) -> "SnapshotLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


def publication_lock(
    state_root: Path | str,
    section_id: str,
    publication_id: str,
    timeout: float = 60.0,
) -> SnapshotLock:
    lock_dir = Path(state_root) / "locks"
    lock_path = lock_dir / f"{section_id}--{publication_id}.lock"
    return SnapshotLock(lock_path, timeout=timeout)
