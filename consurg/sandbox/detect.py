"""Detect available sandbox backends and resolve the best one."""

from __future__ import annotations

import platform
import subprocess


class SandboxBackendError(Exception):
    pass


def _check_docker() -> bool:
    """Check if Docker is available and running."""
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def _check_seatbelt() -> bool:
    """Check if macOS sandbox-exec is available."""
    if platform.system() != "Darwin":
        return False
    try:
        result = subprocess.run(
            ["which", "sandbox-exec"],
            capture_output=True,
            timeout=3,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def _check_wsl2() -> bool:
    """Check if WSL2 is available (Windows only)."""
    if platform.system() != "Windows":
        return False
    try:
        result = subprocess.run(
            ["wsl", "--status"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def detect_backend() -> str:
    """Detect the best available sandbox backend.

    Priority: docker > seatbelt (macOS) > wsl2 (Windows) > none
    """
    if _check_docker():
        return "docker"
    if _check_seatbelt():
        return "seatbelt"
    if _check_wsl2():
        return "wsl2"
    return "none"


def resolve_backend(requested: str) -> str:
    """Resolve a backend request to a concrete backend name.

    Args:
        requested: "auto" | "docker" | "seatbelt" | "wsl2" | "none"

    Returns:
        The resolved backend name.

    Raises:
        SandboxBackendError: If requested backend is not available.
    """
    if requested == "none":
        return "none"

    if requested == "auto":
        return detect_backend()

    # Verify the specific backend is available
    checks = {
        "docker": _check_docker,
        "seatbelt": _check_seatbelt,
        "wsl2": _check_wsl2,
    }

    check_fn = checks.get(requested)
    if check_fn is None:
        raise SandboxBackendError(f"Unknown sandbox backend: {requested!r}")

    if not check_fn():
        raise SandboxBackendError(
            f"Sandbox backend {requested!r} is not available. "
            f"Install it or use --sandbox=auto to detect alternatives."
        )

    return requested
