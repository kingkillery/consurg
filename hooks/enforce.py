#!/usr/bin/env python3
"""Context Surgeon - PreToolUse enforcement hook.

Reads stdin JSON from Claude Code, resolves file tier, and signals
allow (exit 0) or deny (exit 2 with stderr JSON).
"""
import json
import sys
from pathlib import Path

# Allow importing from the consurg package
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from consurg.enforce import resolve_tier
from consurg.scope import load_scope

PATH_FIELDS = {
    "Read": "file_path",
    "Edit": "file_path",
    "Write": "file_path",
    "Grep": "path",
    "Glob": "path",
}


def deny(message: str):
    payload = {
        "hookSpecificOutput": {"permissionDecision": "deny"},
        "systemMessage": message,
    }
    print(json.dumps(payload), file=sys.stderr)
    sys.exit(2)


def main():
    input_data = json.load(sys.stdin)
    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})
    cwd = input_data.get("cwd", ".")

    scope_path = Path(cwd) / ".consurg.yaml"
    scope = load_scope(scope_path)

    if scope is None or not scope.active:
        sys.exit(0)

    path_field = PATH_FIELDS.get(tool_name)
    if not path_field:
        sys.exit(0)

    target = tool_input.get(path_field, "")
    if not target:
        sys.exit(0)

    try:
        target = str(Path(target).relative_to(cwd))
    except ValueError:
        pass

    tier, label = resolve_tier(target, scope)

    if tier <= 1:
        deny(
            f"[CONTEXT SURGEON: ACCESS DENIED]\n"
            f"File: {target}\n"
            f"Tier: {label} (Tier {tier})\n"
            f"Scope: {scope.scope_name}\n"
            f"Reason: Not in working set or dependency graph.\n"
            f"Action: State which file you need and why. User will decide."
        )

    if tier <= 3 and tool_name in ("Edit", "Write"):
        deny(
            f"[CONTEXT SURGEON: WRITE BLOCKED]\n"
            f"File: {target}\n"
            f"Tier: {label} (Tier {tier})\n"
            f"Scope: {scope.scope_name}\n"
            f"Reason: File is {label.lower()} in this scope.\n"
            f"Action: Expand to working_set if write access is needed."
        )

    sys.exit(0)


if __name__ == "__main__":
    main()
