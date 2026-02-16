#!/usr/bin/env python3
"""Context Surgeon - Guard-aware PreToolUse enforcement hook.

Dual-path hook script:
  1. If .consurg-guard.lock exists and guard is reachable → POST /evaluate
  2. Otherwise → fall back to direct resolve_tier() enforcement (same as enforce.py)

Same exit code contract: 0=allow, 2=deny with stderr JSON.
"""

import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path

# Allow importing from the consurg package
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from consurg.constants import COMMAND_FIELD, COMMAND_TOOLS, PATH_FIELDS, READ_TOOLS, WRITE_TOOLS
from consurg.enforce import resolve_tier
from consurg.sandbox.commands import classify_command
from consurg.scope import load_scope

LOCKFILE_NAME = ".consurg-guard.lock"


def deny(message: str):
    payload = {
        "hookSpecificOutput": {"permissionDecision": "deny"},
        "systemMessage": message,
    }
    print(json.dumps(payload), file=sys.stderr)
    sys.exit(2)


def _read_lockfile(cwd: str) -> dict | None:
    """Read guard lockfile, return data if valid."""
    lock_path = Path(cwd) / LOCKFILE_NAME
    if not lock_path.exists():
        return None
    try:
        data = json.loads(lock_path.read_text())
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def _try_guard(port: int, tool_name: str, tool_input: dict, file_path: str,
               request_type: str = "file", **extra) -> dict | None:
    """POST to guard server, return response dict or None on failure."""
    url = f"http://127.0.0.1:{port}/evaluate"
    body = {
        "tool_name": tool_name,
        "tool_input": tool_input,
        "file_path": file_path,
        "request_type": request_type,
        **extra,
    }
    payload = json.dumps(body).encode()

    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=9) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError):
        return None


def _fallback_enforce(tool_name: str, file_path: str, scope, cwd: str):
    """Direct enforcement (same logic as enforce.py)."""
    tier, label = resolve_tier(file_path, scope)

    if scope.explorer and tool_name in READ_TOOLS:
        sys.exit(0)

    if tier <= 1:
        deny(
            f"[CONTEXT SURGEON: ACCESS DENIED]\n"
            f"File: {file_path}\n"
            f"Tier: {label} (Tier {tier})\n"
            f"Scope: {scope.scope_name}\n"
            f"Reason: Not in working set or dependency graph.\n"
            f"Action: State which file you need and why. User will decide."
        )

    if tier <= 3 and tool_name in WRITE_TOOLS:
        deny(
            f"[CONTEXT SURGEON: WRITE BLOCKED]\n"
            f"File: {file_path}\n"
            f"Tier: {label} (Tier {tier})\n"
            f"Scope: {scope.scope_name}\n"
            f"Reason: File is {label.lower()} in this scope.\n"
            f"Action: Expand to working_set if write access is needed."
        )

    sys.exit(0)


def _fallback_command_enforce(tool_name: str, command: str, scope, cwd: str):
    """Direct enforcement for command requests (when guard is not running)."""
    # Use highest tier available (workspace-level command decision)
    tier = 4 if scope.working_set else 0
    decision = classify_command(command, tier, scope)
    if not decision.allow:
        deny(
            f"[CONTEXT SURGEON: COMMAND DENIED]\n"
            f"Command: {command}\n"
            f"Tier: {decision.tier}\n"
            f"Scope: {scope.scope_name}\n"
            f"Reason: {decision.reason}\n"
            f"Action: Adjust scope autonomy or command deny list."
        )
    sys.exit(0)


def main():
    input_data = json.load(sys.stdin)
    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})
    cwd = input_data.get("cwd", ".")

    # Detect if this is a command tool (Bash)
    is_command_tool = tool_name in COMMAND_TOOLS

    if is_command_tool:
        command = tool_input.get(COMMAND_FIELD, "")
        if not command:
            sys.exit(0)

        # Path 1: Try guard server via lockfile
        lock_data = _read_lockfile(cwd)
        if lock_data:
            port = lock_data.get("port")
            if port:
                result = _try_guard(
                    port, tool_name, tool_input, "",
                    request_type="command", command=command,
                )
                if result is not None:
                    if result.get("decision", "deny") == "allow":
                        sys.exit(0)
                    else:
                        deny(result.get("message", f"Command denied: {command}"))

        # Path 2: Fallback to direct enforcement
        scope_path = Path(cwd) / ".consurg.yaml"
        scope = load_scope(scope_path)
        if scope is None or not scope.active:
            sys.exit(0)
        _fallback_command_enforce(tool_name, command, scope, cwd)
        return

    # File-based tool handling (existing logic)
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

    # Path 1: Try guard server via lockfile
    lock_data = _read_lockfile(cwd)
    if lock_data:
        port = lock_data.get("port")
        if port:
            result = _try_guard(port, tool_name, tool_input, target)
            if result is not None:
                decision = result.get("decision", "deny")
                if decision == "allow":
                    sys.exit(0)
                else:
                    message = result.get("message", f"Access denied: {target}")
                    deny(message)

    # Path 2: Fallback to direct enforcement
    scope_path = Path(cwd) / ".consurg.yaml"
    scope = load_scope(scope_path)

    if scope is None or not scope.active:
        sys.exit(0)

    _fallback_enforce(tool_name, target, scope, cwd)


if __name__ == "__main__":
    main()
