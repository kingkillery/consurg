"""Wirer for Claude Code — generates .claude/hooks.json."""

from __future__ import annotations

import json
from pathlib import Path

from consurg.wire.base import BaseWirer, WireResult


class ClaudeWirer(BaseWirer):
    @property
    def name(self) -> str:
        return "Claude Code"

    def _hooks_path(self) -> Path:
        return self.project_dir / ".claude" / "hooks.json"

    def _build_hook_entry(self) -> dict:
        return {
            "type": "command",
            "command": f"python {self.hook_script}",
        }

    def wire(self) -> WireResult:
        hooks_path = self._hooks_path()
        hooks_path.parent.mkdir(parents=True, exist_ok=True)

        # Load existing config or start fresh
        if hooks_path.exists():
            try:
                config = json.loads(hooks_path.read_text())
            except json.JSONDecodeError:
                config = {}
        else:
            config = {}

        if "hooks" not in config:
            config["hooks"] = {}

        hook_entry = self._build_hook_entry()
        pre_tool_hooks = config["hooks"].get("PreToolUse", [])

        # Check if already wired
        for existing in pre_tool_hooks:
            if "enforce_guard" in existing.get("command", ""):
                return WireResult(
                    success=True,
                    message="Already wired to Claude Code",
                    config_path=hooks_path,
                )

        pre_tool_hooks.append(hook_entry)
        config["hooks"]["PreToolUse"] = pre_tool_hooks

        hooks_path.write_text(json.dumps(config, indent=2))
        return WireResult(
            success=True,
            message="Wired to Claude Code (PreToolUse hook)",
            config_path=hooks_path,
        )

    def unwire(self) -> WireResult:
        hooks_path = self._hooks_path()
        if not hooks_path.exists():
            return WireResult(success=True, message="No hooks.json found")

        try:
            config = json.loads(hooks_path.read_text())
        except json.JSONDecodeError:
            return WireResult(success=False, message="Invalid hooks.json")

        hooks = config.get("hooks", {})
        pre_tool = hooks.get("PreToolUse", [])

        filtered = [h for h in pre_tool if "enforce_guard" not in h.get("command", "")]

        if len(filtered) == len(pre_tool):
            return WireResult(success=True, message="No consurg hook found to remove")

        if filtered:
            hooks["PreToolUse"] = filtered
        else:
            hooks.pop("PreToolUse", None)

        config["hooks"] = hooks
        hooks_path.write_text(json.dumps(config, indent=2))
        return WireResult(
            success=True,
            message="Unwired from Claude Code",
            config_path=hooks_path,
        )

    def status(self) -> str:
        hooks_path = self._hooks_path()
        if not hooks_path.exists():
            return "not wired"
        try:
            config = json.loads(hooks_path.read_text())
            pre_tool = config.get("hooks", {}).get("PreToolUse", [])
            for h in pre_tool:
                if "enforce_guard" in h.get("command", ""):
                    return "wired"
        except (json.JSONDecodeError, KeyError):
            pass
        return "not wired"
