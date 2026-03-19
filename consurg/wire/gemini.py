"""Wirer for Gemini CLI — generates MCP server wrapper + adds to ~/.gemini/mcp_config.json.

Since Gemini CLI lacks native hook APIs, we generate a lightweight MCP server script
that wraps scope enforcement as a tool proxy.
"""

from __future__ import annotations

from pathlib import Path

from consurg.wire.base import BaseMcpWirer


class GeminiWirer(BaseMcpWirer):
    @property
    def name(self) -> str:
        return "Gemini CLI"

    def _config_path(self) -> Path:
        return Path.home() / ".gemini" / "mcp_config.json"

    def _wrapper_path(self) -> Path:
        return self.project_dir / "hooks" / "consurg_mcp_gemini.py"
