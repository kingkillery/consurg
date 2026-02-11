"""Tests for the wire system — each wirer generates valid config."""

import json
from pathlib import Path

import pytest

from consurg.wire.claude import ClaudeWirer
from consurg.wire.pk_agent import PkAgentWirer
from consurg.wire.droid import DroidWirer
from consurg.wire.gemini import GeminiWirer
from consurg.wire.codex import CodexWirer


# ---------------------------------------------------------------------------
# Claude wirer
# ---------------------------------------------------------------------------

class TestClaudeWirer:
    def test_wire_creates_hooks_json(self, tmp_path):
        wirer = ClaudeWirer(project_dir=tmp_path)
        result = wirer.wire()
        assert result.success
        assert "Claude Code" in result.message

        hooks_path = tmp_path / ".claude" / "hooks.json"
        assert hooks_path.exists()

        config = json.loads(hooks_path.read_text())
        pre_tool = config["hooks"]["PreToolUse"]
        assert len(pre_tool) == 1
        assert "enforce_guard" in pre_tool[0]["command"]

    def test_wire_idempotent(self, tmp_path):
        wirer = ClaudeWirer(project_dir=tmp_path)
        wirer.wire()
        result = wirer.wire()
        assert result.success
        assert "Already" in result.message

        config = json.loads((tmp_path / ".claude" / "hooks.json").read_text())
        assert len(config["hooks"]["PreToolUse"]) == 1

    def test_unwire_removes_hook(self, tmp_path):
        wirer = ClaudeWirer(project_dir=tmp_path)
        wirer.wire()
        result = wirer.unwire()
        assert result.success
        assert "Unwired" in result.message

        config = json.loads((tmp_path / ".claude" / "hooks.json").read_text())
        assert "PreToolUse" not in config["hooks"]

    def test_unwire_no_config(self, tmp_path):
        wirer = ClaudeWirer(project_dir=tmp_path)
        result = wirer.unwire()
        assert result.success

    def test_status_wired(self, tmp_path):
        wirer = ClaudeWirer(project_dir=tmp_path)
        assert wirer.status() == "not wired"
        wirer.wire()
        assert wirer.status() == "wired"
        wirer.unwire()
        assert wirer.status() == "not wired"

    def test_preserves_existing_hooks(self, tmp_path):
        hooks_path = tmp_path / ".claude" / "hooks.json"
        hooks_path.parent.mkdir(parents=True)
        hooks_path.write_text(json.dumps({
            "hooks": {
                "PreToolUse": [{"type": "command", "command": "echo existing"}],
            }
        }))

        wirer = ClaudeWirer(project_dir=tmp_path)
        wirer.wire()

        config = json.loads(hooks_path.read_text())
        assert len(config["hooks"]["PreToolUse"]) == 2


# ---------------------------------------------------------------------------
# pk-agent wirer
# ---------------------------------------------------------------------------

class TestPkAgentWirer:
    def test_wire_creates_hooks(self, tmp_path):
        wirer = PkAgentWirer(project_dir=tmp_path)
        result = wirer.wire()
        assert result.success

        hooks_path = tmp_path / ".pk-agent" / "hooks.json"
        config = json.loads(hooks_path.read_text())
        assert "tool:start" in config["hooks"]
        assert "enforce_guard" in config["hooks"]["tool:start"][0]["command"]

    def test_wire_idempotent(self, tmp_path):
        wirer = PkAgentWirer(project_dir=tmp_path)
        wirer.wire()
        wirer.wire()
        config = json.loads((tmp_path / ".pk-agent" / "hooks.json").read_text())
        assert len(config["hooks"]["tool:start"]) == 1

    def test_unwire(self, tmp_path):
        wirer = PkAgentWirer(project_dir=tmp_path)
        wirer.wire()
        result = wirer.unwire()
        assert result.success

    def test_status(self, tmp_path):
        wirer = PkAgentWirer(project_dir=tmp_path)
        assert wirer.status() == "not wired"
        wirer.wire()
        assert wirer.status() == "wired"


# ---------------------------------------------------------------------------
# droid wirer
# ---------------------------------------------------------------------------

class TestDroidWirer:
    def test_wire_creates_trusted_dirs(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        wirer = DroidWirer(project_dir=tmp_path / "project")
        result = wirer.wire()
        assert result.success

        config_path = tmp_path / ".puzldai" / "trusted-dirs.json"
        config = json.loads(config_path.read_text())
        assert len(config["trusted_dirs"]) == 1
        assert config["trusted_dirs"][0]["scope"] == "consurg"

    def test_wire_idempotent(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        wirer = DroidWirer(project_dir=tmp_path / "project")
        wirer.wire()
        wirer.wire()
        config = json.loads((tmp_path / ".puzldai" / "trusted-dirs.json").read_text())
        assert len(config["trusted_dirs"]) == 1

    def test_unwire(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        wirer = DroidWirer(project_dir=tmp_path / "project")
        wirer.wire()
        result = wirer.unwire()
        assert result.success
        config = json.loads((tmp_path / ".puzldai" / "trusted-dirs.json").read_text())
        assert len(config["trusted_dirs"]) == 0

    def test_status(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        wirer = DroidWirer(project_dir=tmp_path / "project")
        assert wirer.status() == "not wired"
        wirer.wire()
        assert wirer.status() == "wired"


# ---------------------------------------------------------------------------
# Gemini wirer
# ---------------------------------------------------------------------------

class TestGeminiWirer:
    def test_wire_creates_mcp_config(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        project = tmp_path / "project"
        project.mkdir()
        (project / "hooks").mkdir()

        wirer = GeminiWirer(project_dir=project)
        result = wirer.wire()
        assert result.success

        config_path = tmp_path / ".gemini" / "mcp_config.json"
        config = json.loads(config_path.read_text())
        assert "consurg" in config["mcpServers"]

        wrapper = project / "hooks" / "consurg_mcp_gemini.py"
        assert wrapper.exists()

    def test_wire_idempotent(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        project = tmp_path / "project"
        project.mkdir()
        (project / "hooks").mkdir()

        wirer = GeminiWirer(project_dir=project)
        wirer.wire()
        result = wirer.wire()
        assert "Already" in result.message

    def test_unwire(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        project = tmp_path / "project"
        project.mkdir()
        (project / "hooks").mkdir()

        wirer = GeminiWirer(project_dir=project)
        wirer.wire()
        result = wirer.unwire()
        assert result.success

        wrapper = project / "hooks" / "consurg_mcp_gemini.py"
        assert not wrapper.exists()

    def test_status(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        project = tmp_path / "project"
        project.mkdir()
        (project / "hooks").mkdir()

        wirer = GeminiWirer(project_dir=project)
        assert wirer.status() == "not wired"
        wirer.wire()
        assert wirer.status() == "wired"


# ---------------------------------------------------------------------------
# Codex wirer
# ---------------------------------------------------------------------------

class TestCodexWirer:
    def test_wire_creates_mcp_config(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        project = tmp_path / "project"
        project.mkdir()
        (project / "hooks").mkdir()

        wirer = CodexWirer(project_dir=project)
        result = wirer.wire()
        assert result.success

        config_path = tmp_path / ".codex" / "mcp.json"
        config = json.loads(config_path.read_text())
        assert "consurg" in config["mcpServers"]

        wrapper = project / "hooks" / "consurg_mcp_codex.py"
        assert wrapper.exists()

    def test_unwire(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        project = tmp_path / "project"
        project.mkdir()
        (project / "hooks").mkdir()

        wirer = CodexWirer(project_dir=project)
        wirer.wire()
        result = wirer.unwire()
        assert result.success

    def test_status(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        project = tmp_path / "project"
        project.mkdir()
        (project / "hooks").mkdir()

        wirer = CodexWirer(project_dir=project)
        assert wirer.status() == "not wired"
        wirer.wire()
        assert wirer.status() == "wired"
