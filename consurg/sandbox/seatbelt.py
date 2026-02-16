"""Generate macOS Seatbelt (.sb) profiles from consurg scope tiers."""

from __future__ import annotations

from pathlib import Path

from consurg.scope import Scope


def _resolve_paths(patterns: list[str], project_root: Path) -> list[Path]:
    """Resolve glob patterns to actual file/dir paths under project_root."""
    paths: set[Path] = set()
    for pattern in patterns:
        for match in project_root.glob(pattern):
            paths.add(match)
        # Also try the literal pattern as a path
        candidate = project_root / pattern
        if candidate.exists():
            paths.add(candidate)
    return sorted(paths)


def _sb_subpath(path: Path) -> str:
    """Format a path as a Seatbelt subpath literal."""
    return f'(subpath "{path}")'


def generate_seatbelt_profile(
    scope: Scope,
    project_root: Path,
) -> str:
    """Generate a macOS Seatbelt sandbox profile from scope tier definitions.

    Mapping:
      T4 (working_set) → file-write* + file-read-data
      T3 (reference)   → file-read-data only
      T2/T1/T0         → denied (implicit from deny default)

    Network:
      allowlist → allow network-outbound only to listed hosts
      denylist  → allow network* (filtering external)
      unrestricted → allow network*
    """
    lines = [
        "(version 1)",
        "(deny default)",
        "",
        ";; Allow basic system operations",
        "(allow process-exec)",
        "(allow process-fork)",
        "(allow sysctl-read)",
        "(allow mach-lookup)",
        "",
    ]

    # T4: read-write access
    t4_paths = _resolve_paths(scope.working_set, project_root)
    if t4_paths:
        lines.append(";; T4 (working_set): full read-write")
        for p in t4_paths:
            lines.append(f"(allow file-read-data {_sb_subpath(p)})")
            lines.append(f"(allow file-write* {_sb_subpath(p)})")
        lines.append("")

    # T3: read-only access
    t3_paths = _resolve_paths(scope.reference, project_root)
    if t3_paths:
        lines.append(";; T3 (reference): read-only")
        for p in t3_paths:
            lines.append(f"(allow file-read-data {_sb_subpath(p)})")
        lines.append("")

    # T2: signature-only (read metadata/headers)
    t2_paths = _resolve_paths(scope.signatures, project_root)
    if t2_paths:
        lines.append(";; T2 (signatures): read-only")
        for p in t2_paths:
            lines.append(f"(allow file-read-data {_sb_subpath(p)})")
        lines.append("")

    # Network rules
    network = scope.sandbox.network
    lines.append(";; Network rules")
    if network.policy == "unrestricted":
        lines.append("(allow network*)")
    elif network.policy == "allowlist" and network.allow:
        for host in network.allow:
            lines.append(f'(allow network-outbound (remote tcp "{host}"))')
    elif network.policy == "denylist":
        lines.append("(allow network*)")
        for host in network.deny:
            lines.append(f'(deny network-outbound (remote tcp "{host}"))')
    else:
        # No network access (empty allowlist or default)
        lines.append(";; No network access")
    lines.append("")

    # Temp directory access (needed for most operations)
    lines.append(";; Temp directory access")
    lines.append('(allow file-read-data (subpath "/tmp"))')
    lines.append('(allow file-write* (subpath "/tmp"))')
    lines.append("")

    return "\n".join(lines)
