#!/usr/bin/env python3
"""Context Surgeon - PreToolUse enforcement hook.

Reads stdin JSON from Claude Code, resolves file tier, and signals
allow (exit 0) or deny (exit 2 with stderr JSON).
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Allow importing from the consurg package
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from consurg.constants import PATH_FIELDS, READ_TOOLS, WRITE_TOOLS
from consurg.enforce import resolve_tier
from consurg.scope import load_scope


def log_violation(cwd: str, tool_name: str, target: str, label: str, scope_name: str):
    if not os.environ.get("CONSURG_LOG"):
        return
    log_path = Path(cwd) / ".consurg-violations.log"
    timestamp = datetime.now(timezone.utc).isoformat()
    line = f"[{timestamp}] DENIED tool={tool_name} file={target} tier={label} scope={scope_name}\n"
    with open(log_path, "a") as f:
        f.write(line)


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

    # Explorer mode: allow read tools on all files, still block writes outside working_set
    if scope.explorer and tool_name in READ_TOOLS:
        sys.exit(0)

    if tier <= 1:
        log_violation(cwd, tool_name, target, label, scope.scope_name)
        deny(
            f"[CONTEXT SURGEON: ACCESS DENIED]\n"
            f"File: {target}\n"
            f"Tier: {label} (Tier {tier})\n"
            f"Scope: {scope.scope_name}\n"
            f"Reason: Not in working set or dependency graph.\n"
            f"Action: State which file you need and why. User will decide."
        )

    if tier <= 3 and tool_name in WRITE_TOOLS:
        log_violation(cwd, tool_name, target, label, scope.scope_name)
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
