"""File lock for full validation pipeline runs."""

from __future__ import annotations

import os
from pathlib import Path


class PipelineLock:
    """Prevent concurrent full-validation runs in the same output directory."""

    def __init__(self, lock_path: str | Path) -> None:
        self.lock_path = Path(lock_path)
        self._fd: int | None = None

    def acquire(self) -> None:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._fd = os.open(str(self.lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(self._fd, str(os.getpid()).encode("ascii"))
        except FileExistsError as exc:
            raise RuntimeError(f"pipeline lock already held: {self.lock_path}") from exc

    def release(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
        self.lock_path.unlink(missing_ok=True)

    def __enter__(self) -> "PipelineLock":
        self.acquire()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()

