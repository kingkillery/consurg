"""Generate Docker container profiles from consurg scope tiers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from consurg.scope import Scope, pattern_matches


@dataclass
class VolumeMount:
    host_path: str
    container_path: str
    mode: str = "rw"  # "rw" or "ro"


@dataclass
class DockerProfile:
    image: str = "python:3.12-slim"
    volumes: list[VolumeMount] = field(default_factory=list)
    network_mode: str = "none"  # "none" | "bridge" | "host"
    env: dict[str, str] = field(default_factory=dict)
    working_dir: str = "/workspace"

    def to_run_args(self) -> list[str]:
        """Serialize to docker run CLI arguments."""
        args = ["docker", "run", "--rm"]
        args.extend(["--network", self.network_mode])
        args.extend(["-w", self.working_dir])
        for vol in self.volumes:
            bind = f"{vol.host_path}:{vol.container_path}:{vol.mode}"
            args.extend(["-v", bind])
        for key, val in self.env.items():
            args.extend(["-e", f"{key}={val}"])
        args.append(self.image)
        return args


def _resolve_dirs(patterns: list[str], project_root: Path) -> list[Path]:
    """Resolve glob patterns to actual directories under project_root."""
    dirs: set[Path] = set()
    for pattern in patterns:
        # Direct directory reference
        candidate = project_root / pattern.replace("*", "").rstrip("/")
        if candidate.is_dir():
            dirs.add(candidate)
            continue
        # Glob to find matching files, collect their parent dirs
        for match in project_root.glob(pattern):
            if match.is_file():
                dirs.add(match.parent)
            elif match.is_dir():
                dirs.add(match)
    return sorted(dirs)


def generate_docker_profile(
    scope: Scope,
    project_root: Path,
    image: str = "python:3.12-slim",
) -> DockerProfile:
    """Generate a Docker profile from scope tier definitions.

    Mapping:
      T4 (working_set) → rw volume mounts
      T3 (reference)   → ro volume mounts
      T2/T1/T0         → not mounted (invisible)
    """
    profile = DockerProfile(image=image)
    container_base = PurePosixPath("/workspace")

    # T4: read-write mounts
    for d in _resolve_dirs(scope.working_set, project_root):
        rel = d.relative_to(project_root)
        profile.volumes.append(VolumeMount(
            host_path=str(d),
            container_path=str(container_base / rel.as_posix()),
            mode="rw",
        ))

    # T3: read-only mounts
    for d in _resolve_dirs(scope.reference, project_root):
        rel = d.relative_to(project_root)
        # Skip if already mounted as rw
        if any(v.host_path == str(d) for v in profile.volumes):
            continue
        profile.volumes.append(VolumeMount(
            host_path=str(d),
            container_path=str(container_base / rel.as_posix()),
            mode="ro",
        ))

    # Network mode from sandbox config
    network = scope.sandbox.network
    if network.policy == "unrestricted":
        profile.network_mode = "bridge"
    elif network.policy == "allowlist" and not network.allow:
        profile.network_mode = "none"
    elif network.policy == "denylist":
        profile.network_mode = "bridge"  # filtering done at iptables level
    else:
        profile.network_mode = "none"

    # Environment
    profile.env["CONSURG_SCOPE"] = scope.scope_name
    profile.env["CONSURG_AUTONOMY"] = str(scope.sandbox.autonomy)

    return profile
