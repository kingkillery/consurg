from dataclasses import dataclass, field
from pathlib import Path

import yaml


class ScopeError(Exception):
    pass


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


def load_scope(path: Path) -> Scope | None:
    scope_path = Path(path)
    if not scope_path.exists():
        return None

    with open(scope_path) as f:
        data = yaml.safe_load(f)

    if data is None:
        return None

    version = data.get("version")
    if version != 1:
        raise ScopeError(f"Unsupported scope version: {version} (expected 1)")

    active = data.get("active", True)
    if not isinstance(active, bool):
        raise ScopeError(f"'active' must be a boolean, got {type(active).__name__}")

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
    )
