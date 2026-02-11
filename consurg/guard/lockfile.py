"""Lockfile management for guard port/PID discovery.

Hook scripts read .consurg-guard.lock to find the running guard's port.
Stale locks are detected via PID liveness check.
"""

from __future__ import annotations

import json
import os
from pathlib import Path


LOCKFILE_NAME = ".consurg-guard.lock"


class GuardLockfile:
    """Manages the .consurg-guard.lock file."""

    def __init__(self, directory: str | Path | None = None):
        self.directory = Path(directory) if directory else Path.cwd()
        self.path = self.directory / LOCKFILE_NAME

    def write(self, port: int, scope_name: str) -> None:
        """Write lockfile with current PID and port."""
        data = {
            "pid": os.getpid(),
            "port": port,
            "scope": scope_name,
        }
        self.path.write_text(json.dumps(data, indent=2))

    def read(self) -> dict | None:
        """Read lockfile. Returns None if missing or invalid."""
        if not self.path.exists():
            return None
        try:
            data = json.loads(self.path.read_text())
            if not isinstance(data, dict):
                return None
            return data
        except (json.JSONDecodeError, OSError):
            return None

    def is_alive(self) -> bool:
        """Check if the guard process from the lockfile is still running."""
        data = self.read()
        if data is None:
            return False
        pid = data.get("pid")
        if pid is None:
            return False
        return _pid_exists(pid)

    def remove(self) -> None:
        """Remove the lockfile if it exists."""
        if self.path.exists():
            self.path.unlink(missing_ok=True)

    def get_port(self) -> int | None:
        """Read the guard port from lockfile, if alive."""
        if not self.is_alive():
            return None
        data = self.read()
        return data.get("port") if data else None


def _pid_exists(pid: int) -> bool:
    """Check whether a PID is alive (cross-platform)."""
    if os.name == "nt":
        # Windows: use ctypes to check process
        import ctypes
        kernel32 = ctypes.windll.kernel32
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return False
    else:
        # Unix: signal 0 checks existence
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True  # Process exists but we can't signal it
