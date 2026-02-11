#!/usr/bin/env python3
"""
Custom enforcement hook for unsupported AI tools.

Reads tool call JSON from stdin, evaluates file access against
the active .consurg.yaml scope, and exits with:
  - 0: allow
  - 2: deny (with structured error on stderr)

Customize the stdin JSON parsing for the target tool's hook protocol.

NOTE: The sys.path line below assumes this script is in the project's
hooks/ directory (two levels below the consurg package root). Adjust
if copied elsewhere, or ensure consurg is installed as a package.
"""
import json
import sys
from pathlib import Path

# Add consurg to path (adjust if installed as package)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from consurg.enforce import resolve_tier
from consurg.scope import load_scope


def main():
    # Parse tool call from stdin
    # Adapt this section for your tool's hook protocol
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        sys.exit(0)  # Can't parse = allow (fail open)

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    cwd = data.get("cwd", str(Path.cwd()))

    # Extract file path (adapt field names for your tool)
    file_path = tool_input.get("file_path") or tool_input.get("path", "")
    if not file_path:
        sys.exit(0)  # No file target = allow

    # Load scope
    scope = load_scope(Path(cwd) / ".consurg.yaml")
    if scope is None or not scope.active:
        sys.exit(0)  # No scope or inactive = allow

    # Normalize to relative path
    try:
        rel_path = str(Path(file_path).relative_to(cwd))
    except ValueError:
        rel_path = file_path  # Already relative

    # Normalize path separators
    rel_path = rel_path.replace("\\", "/")

    # Resolve tier
    tier, label = resolve_tier(rel_path, scope)

    # Decide: allow or deny
    is_write = tool_name in ("Edit", "Write")

    if tier >= 4:
        sys.exit(0)  # T4: full access
    elif tier >= 2 and not is_write:
        sys.exit(0)  # T2-T3: reads allowed
    else:
        # Deny with structured error
        error = {
            "hookSpecificOutput": {
                "permissionDecision": "deny"
            },
            "systemMessage": (
                f"[CONTEXT SURGEON: ACCESS DENIED]\n"
                f"File: {rel_path}\n"
                f"Tier: {label} (Tier {tier})\n"
                f"Scope: {scope.scope_name}\n"
                f"Reason: {'Write blocked on read-only file' if tier >= 2 else 'Not in scope'}.\n"
                f"Action: State which file you need and why. User will decide."
            ),
        }
        sys.stderr.write(json.dumps(error))
        sys.exit(2)


if __name__ == "__main__":
    main()
