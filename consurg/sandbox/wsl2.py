"""Generate WSL2 filesystem mapping profiles from consurg scope tiers."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from consurg.scope import Scope


@dataclass
class WSL2Profile:
    setup_commands: list[str] = field(default_factory=list)
    teardown_commands: list[str] = field(default_factory=list)
    env_vars: dict[str, str] = field(default_factory=dict)
    wsl_distro: str = "Ubuntu"
    workspace_dir: str = "/tmp/consurg-sandbox"


def windows_to_wsl_path(win_path: str) -> str:
    """Convert a Windows path to WSL2 /mnt/ path.

    C:\\Users\\foo\\bar → /mnt/c/Users/foo/bar
    D:\\data → /mnt/d/data
    """
    normalized = win_path.replace("\\", "/")
    # Match drive letter pattern
    match = re.match(r"^([A-Za-z]):/(.*)$", normalized)
    if match:
        drive = match.group(1).lower()
        rest = match.group(2)
        return f"/mnt/{drive}/{rest}"
    # Already a Unix-style path or relative
    return normalized


def _resolve_dirs(patterns: list[str], project_root: Path) -> list[Path]:
    """Resolve glob patterns to actual directories under project_root."""
    dirs: set[Path] = set()
    for pattern in patterns:
        candidate = project_root / pattern.replace("*", "").rstrip("/")
        if candidate.is_dir():
            dirs.add(candidate)
            continue
        for match in project_root.glob(pattern):
            if match.is_file():
                dirs.add(match.parent)
            elif match.is_dir():
                dirs.add(match)
    return sorted(dirs)


def generate_wsl2_profile(
    scope: Scope,
    project_root: Path,
    wsl_distro: str = "Ubuntu",
) -> WSL2Profile:
    """Generate a WSL2 profile from scope tier definitions.

    Mapping:
      T4 (working_set) → bind mount (rw)
      T3 (reference)   → bind mount (ro)
      T2/T1/T0         → not mounted (invisible)

    The profile generates setup/teardown commands to be run inside WSL2.
    """
    profile = WSL2Profile(wsl_distro=wsl_distro)
    ws = profile.workspace_dir

    # Setup: create workspace
    profile.setup_commands.append(f"mkdir -p {ws}")

    mounted_hosts: set[str] = set()

    # T4: read-write bind mounts
    for d in _resolve_dirs(scope.working_set, project_root):
        wsl_src = windows_to_wsl_path(str(d))
        rel = d.relative_to(project_root)
        target = f"{ws}/{PurePosixPath(rel)}"
        profile.setup_commands.append(f"mkdir -p {target}")
        profile.setup_commands.append(f"mount --bind {wsl_src} {target}")
        mounted_hosts.add(str(d))

    # T3: read-only bind mounts
    for d in _resolve_dirs(scope.reference, project_root):
        if str(d) in mounted_hosts:
            continue
        wsl_src = windows_to_wsl_path(str(d))
        rel = d.relative_to(project_root)
        target = f"{ws}/{PurePosixPath(rel)}"
        profile.setup_commands.append(f"mkdir -p {target}")
        profile.setup_commands.append(f"mount --bind -o ro {wsl_src} {target}")
        mounted_hosts.add(str(d))

    # Teardown: unmount in reverse order and clean up
    for cmd in reversed(profile.setup_commands):
        if cmd.startswith("mount"):
            target = cmd.split()[-1]
            profile.teardown_commands.append(f"umount {target} 2>/dev/null || true")
    profile.teardown_commands.append(f"rm -rf {ws}")

    # Environment
    profile.env_vars["CONSURG_SCOPE"] = scope.scope_name
    profile.env_vars["CONSURG_AUTONOMY"] = str(scope.sandbox.autonomy)
    profile.env_vars["CONSURG_WORKSPACE"] = ws

    return profile
