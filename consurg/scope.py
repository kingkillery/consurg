from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath

import yaml


class ScopeError(Exception):
    pass


def pattern_matches(file_path: str, pattern: str) -> bool:
    normalized_file = file_path.replace("\\", "/")
    normalized_pattern = pattern.replace("\\", "/")

    # Strip leading ./
    while normalized_file.startswith("./"):
        normalized_file = normalized_file[2:]
    while normalized_pattern.startswith("./"):
        normalized_pattern = normalized_pattern[2:]

    if not normalized_file or not normalized_pattern:
        return False

    # Original two-algorithm check (preserves existing behavior)
    if fnmatch(normalized_file, normalized_pattern) or PurePosixPath(
        normalized_file
    ).match(normalized_pattern):
        return True

    # Branch: pattern contains **
    if "**" in normalized_pattern:
        return PurePosixPath(normalized_file).match(f"**/{normalized_pattern}")

    # Branch: pattern contains / (path-like pattern)
    if "/" in normalized_pattern:
        if PurePosixPath(normalized_file).match(f"**/{normalized_pattern}"):
            return True
        if PurePosixPath(normalized_file).match(f"{normalized_pattern}/**"):
            return True
        return False

    # Branch: simple name/glob — match against each path component
    parts = normalized_file.split("/")
    return any(fnmatch(part, normalized_pattern) for part in parts)


@dataclass
class NetworkPolicy:
    policy: str = "unrestricted"  # "allowlist" | "denylist" | "unrestricted"
    allow: list[str] = field(default_factory=list)
    deny: list[str] = field(default_factory=list)


@dataclass
class SandboxConfig:
    backend: str = "none"  # "auto" | "docker" | "seatbelt" | "wsl2" | "none"
    autonomy: int = 2  # 0=recon, 1=safe-edits, 2=dev, 3=risky
    network: NetworkPolicy = field(default_factory=NetworkPolicy)
    command_deny: list[str] = field(default_factory=list)


@dataclass
class Scope:
    version: int = 1
    scope_name: str = ""
    active: bool = True
    reason: str = ""
    working_set: list[str] = field(default_factory=list)
    reference: list[str] = field(default_factory=list)
    signatures: list[str] = field(default_factory=list)
    visible: list[str] = field(default_factory=list)
    dynamic_deps: list[str] = field(default_factory=list)
    explorer: bool = False
    sandbox: SandboxConfig = field(default_factory=SandboxConfig)


def load_scope(path: Path) -> Scope | None:
    scope_path = Path(path)
    if not scope_path.exists():
        return None

    with open(scope_path) as f:
        data = yaml.safe_load(f)

    if data is None:
        return None

    version = data.get("version")
    if version not in (1, 2):
        raise ScopeError(f"Unsupported scope version: {version} (expected 1 or 2)")

    active = data.get("active", True)
    if not isinstance(active, bool):
        raise ScopeError(f"'active' must be a boolean, got {type(active).__name__}")

    sandbox = SandboxConfig()
    if version == 2:
        sb = data.get("sandbox", {})
        net = sb.get("network", {})
        sandbox = SandboxConfig(
            backend=sb.get("backend", "none"),
            autonomy=sb.get("autonomy", 2),
            network=NetworkPolicy(
                policy=net.get("policy", "unrestricted"),
                allow=net.get("allow", []),
                deny=net.get("deny", []),
            ),
            command_deny=sb.get("commands", {}).get("deny", []),
        )

    return Scope(
        version=version,
        scope_name=data.get("scope", ""),
        active=active,
        reason=data.get("reason", ""),
        working_set=data.get("working_set", []),
        reference=data.get("reference", []),
        signatures=data.get("signatures", []),
        visible=data.get("visible", []),
        dynamic_deps=data.get("dynamic_deps", []),
        explorer=data.get("explorer", False),
        sandbox=sandbox,
    )


def _parent_tier(file: str, parent: Scope) -> int:
    tiers = [
        (4, parent.working_set),
        (3, parent.reference),
        (2, parent.signatures),
        (1, parent.visible),
    ]
    for tier_num, patterns in tiers:
        for pattern in patterns:
            if pattern_matches(file, pattern):
                return tier_num
    return 0


def narrow_scope(parent: Scope, child_files: list[str]) -> Scope:
    for f in child_files:
        if _parent_tier(f, parent) == 0:
            raise ScopeError(f"File '{f}' is not in parent scope")

    child = Scope(
        scope_name=f"{parent.scope_name}/child",
        active=parent.active,
        explorer=parent.explorer,
    )

    tier_lists = {
        4: child.working_set,
        3: child.reference,
        2: child.signatures,
        1: child.visible,
    }

    for f in child_files:
        tier = _parent_tier(f, parent)
        tier_lists[tier].append(f)

    return child


def detect_write_conflicts(scopes: list[Scope]) -> list[str]:
    conflicts: list[str] = []
    for i, a in enumerate(scopes):
        for b in scopes[i + 1:]:
            for pattern_a in a.working_set:
                for pattern_b in b.working_set:
                    if pattern_matches(pattern_a, pattern_b) or pattern_matches(pattern_b, pattern_a):
                        if pattern_a not in conflicts:
                            conflicts.append(pattern_a)
                        if pattern_b != pattern_a and pattern_b not in conflicts:
                            conflicts.append(pattern_b)
    return conflicts
