"""Wirer for Codex CLI — generates MCP server wrapper + adds to ~/.codex/mcp.json.

Like Gemini, Codex CLI lacks native hook APIs so we generate an MCP server wrapper.
"""

from __future__ import annotations

from pathlib import Path

from consurg.wire.base import BaseMcpWirer


class CodexWirer(BaseMcpWirer):
    @property
    def name(self) -> str:
        return "Codex CLI"

    def _config_path(self) -> Path:
        return Path.home() / ".codex" / "mcp.json"

    def _wrapper_path(self) -> Path:
        return self.project_dir / "hooks" / "consurg_mcp_codex.py"
