"""Wirer for pk-agent — generates .pk-agent/hooks.json with tool:start event."""

from __future__ import annotations

import json
from pathlib import Path

from consurg.wire.base import BaseWirer, WireResult


class PkAgentWirer(BaseWirer):
    @property
    def name(self) -> str:
        return "pk-agent"

    def _hooks_path(self) -> Path:
        return self.project_dir / ".pk-agent" / "hooks.json"

    def wire(self) -> WireResult:
        hooks_path = self._hooks_path()
        hooks_path.parent.mkdir(parents=True, exist_ok=True)

        if hooks_path.exists():
            try:
                config = json.loads(hooks_path.read_text())
            except json.JSONDecodeError:
                config = {}
        else:
            config = {}

        if "hooks" not in config:
            config["hooks"] = {}

        hook_entry = {
            "type": "command",
            "command": f"python {self.hook_script}",
        }

        tool_start_hooks = config["hooks"].get("tool:start", [])

        for existing in tool_start_hooks:
            if "enforce_guard" in existing.get("command", ""):
                return WireResult(
                    success=True,
                    message="Already wired to pk-agent",
                    config_path=hooks_path,
                )

        tool_start_hooks.append(hook_entry)
        config["hooks"]["tool:start"] = tool_start_hooks

        hooks_path.write_text(json.dumps(config, indent=2))
        return WireResult(
            success=True,
            message="Wired to pk-agent (tool:start hook)",
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
        tool_start = hooks.get("tool:start", [])

        filtered = [h for h in tool_start if "enforce_guard" not in h.get("command", "")]

        if len(filtered) == len(tool_start):
            return WireResult(success=True, message="No consurg hook found to remove")

        if filtered:
            hooks["tool:start"] = filtered
        else:
            hooks.pop("tool:start", None)

        config["hooks"] = hooks
        hooks_path.write_text(json.dumps(config, indent=2))
        return WireResult(
            success=True,
            message="Unwired from pk-agent",
            config_path=hooks_path,
        )

    def status(self) -> str:
        hooks_path = self._hooks_path()
        if not hooks_path.exists():
            return "not wired"
        try:
            config = json.loads(hooks_path.read_text())
            tool_start = config.get("hooks", {}).get("tool:start", [])
            for h in tool_start:
                if "enforce_guard" in h.get("command", ""):
                    return "wired"
        except (json.JSONDecodeError, KeyError):
            pass
        return "not wired"
