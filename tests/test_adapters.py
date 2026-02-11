import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from consurg.adapters import (
    generate_aider_args,
    generate_claude_scope,
    generate_cursor_rules,
    generate_generic_prompt,
)
from consurg.cli import app
from consurg.scope import Scope, ScopeError, detect_write_conflicts, narrow_scope

runner = CliRunner()


@pytest.fixture
def in_tmp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _make_scope(**kwargs) -> Scope:
    defaults = {
        "scope_name": "test",
        "working_set": ["src/*.py"],
        "reference": ["docs/*.md"],
        "signatures": ["types/*.pyi"],
        "visible": ["README.md"],
    }
    defaults.update(kwargs)
    return Scope(**defaults)


# --- Adapter tests ---


class TestClaudeAdapter:
    def test_generates_markdown(self):
        scope = _make_scope()
        result = generate_claude_scope(scope)
        assert "# Context Surgeon Scope: test" in result
        assert "## Working Set (READ-WRITE)" in result
        assert "- `src/*.py`" in result

    def test_includes_all_tiers(self):
        scope = _make_scope()
        result = generate_claude_scope(scope)
        assert "READ-WRITE" in result
        assert "READ-ONLY" in result
        assert "SIGNATURE-ONLY" in result
        assert "EXISTENCE-ONLY" in result

    def test_omits_empty_tiers(self):
        scope = Scope(scope_name="minimal", working_set=["main.py"])
        result = generate_claude_scope(scope)
        assert "READ-ONLY" not in result
        assert "SIGNATURE" not in result
        assert "EXISTENCE" not in result

    def test_ends_with_blocked_warning(self):
        scope = _make_scope()
        result = generate_claude_scope(scope)
        assert "BLOCKED" in result


class TestCursorAdapter:
    def test_generates_rules(self):
        scope = _make_scope()
        result = generate_cursor_rules(scope)
        assert "allow: src/*.py" in result
        assert "read-only: docs/*.md" in result

    def test_includes_header(self):
        scope = _make_scope()
        result = generate_cursor_rules(scope)
        assert "Context Surgeon Scope: test" in result

    def test_omits_empty_tiers(self):
        scope = Scope(scope_name="minimal", working_set=["main.py"])
        result = generate_cursor_rules(scope)
        assert "read-only:" not in result
        assert "signature:" not in result


class TestAiderAdapter:
    def test_generates_file_flags(self):
        scope = _make_scope()
        result = generate_aider_args(scope)
        assert result == ["--file", "src/*.py", "--read", "docs/*.md"]

    def test_empty_scope(self):
        scope = Scope(scope_name="empty")
        result = generate_aider_args(scope)
        assert result == []

    def test_multiple_files(self):
        scope = Scope(working_set=["a.py", "b.py"], reference=["c.py"])
        result = generate_aider_args(scope)
        assert result == ["--file", "a.py", "--file", "b.py", "--read", "c.py"]


class TestGenericAdapter:
    def test_generates_prompt(self):
        scope = _make_scope()
        result = generate_generic_prompt(scope)
        assert "[SCOPE: test]" in result
        assert "Tier 4 - READ-WRITE:" in result
        assert "  src/*.py" in result

    def test_includes_blocked_notice(self):
        scope = _make_scope()
        result = generate_generic_prompt(scope)
        assert "Tier 0 - BLOCKED" in result


# --- CLI export tests ---


class TestExportCommand:
    def test_export_claude(self, in_tmp):
        runner.invoke(app, ["init", "export-test"])
        runner.invoke(app, ["add", "src/*.py"])
        result = runner.invoke(app, ["export", "--format", "claude"])
        assert result.exit_code == 0
        assert "Working Set" in result.output

    def test_export_cursor(self, in_tmp):
        runner.invoke(app, ["init", "export-test"])
        runner.invoke(app, ["add", "src/*.py"])
        result = runner.invoke(app, ["export", "--format", "cursor"])
        assert result.exit_code == 0
        assert "allow: src/*.py" in result.output

    def test_export_aider(self, in_tmp):
        runner.invoke(app, ["init", "export-test"])
        runner.invoke(app, ["add", "src/*.py"])
        runner.invoke(app, ["add", "--read", "docs/*.md"])
        result = runner.invoke(app, ["export", "--format", "aider"])
        assert result.exit_code == 0
        assert "--file" in result.output

    def test_export_generic(self, in_tmp):
        runner.invoke(app, ["init", "export-test"])
        runner.invoke(app, ["add", "src/*.py"])
        result = runner.invoke(app, ["export", "--format", "generic"])
        assert result.exit_code == 0
        assert "SCOPE:" in result.output

    def test_export_invalid_format(self, in_tmp):
        runner.invoke(app, ["init"])
        result = runner.invoke(app, ["export", "--format", "invalid"])
        assert result.exit_code == 1

    def test_export_no_scope(self, in_tmp):
        result = runner.invoke(app, ["export", "--format", "claude"])
        assert result.exit_code == 1


# --- narrow_scope tests ---


class TestNarrowScope:
    def test_basic_narrowing(self):
        parent = _make_scope()
        child = narrow_scope(parent, ["src/main.py"])
        assert "src/main.py" in child.working_set
        assert child.reference == []

    def test_preserves_parent_tier(self):
        parent = _make_scope()
        child = narrow_scope(parent, ["src/main.py", "docs/guide.md"])
        assert "src/main.py" in child.working_set
        assert "docs/guide.md" in child.reference

    def test_rejects_files_outside_parent(self):
        parent = _make_scope()
        with pytest.raises(ScopeError, match="not in parent scope"):
            narrow_scope(parent, ["secret.key"])

    def test_monotonic_narrowing(self):
        parent = _make_scope()
        child = narrow_scope(parent, ["docs/api.md"])
        # docs/*.md is reference (tier 3) in parent, child should keep it there
        assert "docs/api.md" in child.reference
        assert "docs/api.md" not in child.working_set

    def test_child_scope_name(self):
        parent = _make_scope(scope_name="parent")
        child = narrow_scope(parent, ["src/main.py"])
        assert child.scope_name == "parent/child"

    def test_inherits_active_and_explorer(self):
        parent = _make_scope(active=True, explorer=True)
        child = narrow_scope(parent, ["src/main.py"])
        assert child.active is True
        assert child.explorer is True


# --- Explorer mode tests ---


class TestExplorerMode:
    @pytest.fixture
    def hook_path(self):
        return Path(__file__).resolve().parent.parent / "hooks" / "enforce.py"

    def _run_hook(self, hook_path, tmp_path, tool_name, file_path, scope_data):
        scope_file = tmp_path / ".consurg.yaml"
        scope_file.write_text(yaml.dump(scope_data))

        input_data = {
            "tool_name": tool_name,
            "tool_input": {"file_path": file_path, "path": file_path},
            "cwd": str(tmp_path),
        }

        result = subprocess.run(
            [sys.executable, str(hook_path)],
            input=json.dumps(input_data),
            capture_output=True,
            text=True,
        )
        return result

    def test_explorer_allows_read_on_blocked_file(self, tmp_path, hook_path):
        scope_data = {
            "version": 1,
            "scope": "explorer-test",
            "active": True,
            "working_set": ["src/*.py"],
            "reference": [],
            "signatures": [],
            "visible": [],
            "explorer": True,
        }
        result = self._run_hook(hook_path, tmp_path, "Read", "secret.txt", scope_data)
        assert result.returncode == 0

    def test_explorer_blocks_write_on_non_working_set(self, tmp_path, hook_path):
        scope_data = {
            "version": 1,
            "scope": "explorer-test",
            "active": True,
            "working_set": ["src/*.py"],
            "reference": [],
            "signatures": [],
            "visible": [],
            "explorer": True,
        }
        result = self._run_hook(hook_path, tmp_path, "Edit", "secret.txt", scope_data)
        assert result.returncode == 2

    def test_non_explorer_blocks_read_on_blocked_file(self, tmp_path, hook_path):
        scope_data = {
            "version": 1,
            "scope": "strict-test",
            "active": True,
            "working_set": ["src/*.py"],
            "reference": [],
            "signatures": [],
            "visible": [],
            "explorer": False,
        }
        result = self._run_hook(hook_path, tmp_path, "Read", "secret.txt", scope_data)
        assert result.returncode == 2


# --- Write conflict detection tests ---


class TestWriteConflicts:
    def test_detects_identical_patterns(self):
        a = Scope(scope_name="a", working_set=["src/*.py"])
        b = Scope(scope_name="b", working_set=["src/*.py"])
        conflicts = detect_write_conflicts([a, b])
        assert "src/*.py" in conflicts

    def test_no_conflict_different_patterns(self):
        a = Scope(scope_name="a", working_set=["src/*.py"])
        b = Scope(scope_name="b", working_set=["tests/*.py"])
        conflicts = detect_write_conflicts([a, b])
        assert conflicts == []

    def test_detects_glob_overlap(self):
        a = Scope(scope_name="a", working_set=["src/main.py"])
        b = Scope(scope_name="b", working_set=["src/*.py"])
        conflicts = detect_write_conflicts([a, b])
        assert len(conflicts) > 0

    def test_no_conflict_single_scope(self):
        a = Scope(scope_name="a", working_set=["src/*.py"])
        conflicts = detect_write_conflicts([a])
        assert conflicts == []

    def test_three_way_conflict(self):
        a = Scope(scope_name="a", working_set=["shared.py"])
        b = Scope(scope_name="b", working_set=["shared.py"])
        c = Scope(scope_name="c", working_set=["shared.py"])
        conflicts = detect_write_conflicts([a, b, c])
        assert "shared.py" in conflicts


# --- Violation logging tests ---


class TestViolationLogging:
    @pytest.fixture
    def hook_path(self):
        return Path(__file__).resolve().parent.parent / "hooks" / "enforce.py"

    def test_logs_when_env_set(self, tmp_path, hook_path, monkeypatch):
        monkeypatch.setenv("CONSURG_LOG", "1")
        scope_data = {
            "version": 1,
            "scope": "log-test",
            "active": True,
            "working_set": ["src/*.py"],
            "reference": [],
            "signatures": [],
            "visible": [],
        }
        scope_file = tmp_path / ".consurg.yaml"
        scope_file.write_text(yaml.dump(scope_data))

        input_data = {
            "tool_name": "Read",
            "tool_input": {"file_path": "secret.txt"},
            "cwd": str(tmp_path),
        }

        subprocess.run(
            [sys.executable, str(hook_path)],
            input=json.dumps(input_data),
            capture_output=True,
            text=True,
            env={**os.environ, "CONSURG_LOG": "1"},
        )

        log_file = tmp_path / ".consurg-violations.log"
        assert log_file.exists()
        content = log_file.read_text()
        assert "DENIED" in content
        assert "tool=Read" in content
        assert "file=secret.txt" in content
        assert "scope=log-test" in content

    def test_no_log_without_env(self, tmp_path, hook_path):
        scope_data = {
            "version": 1,
            "scope": "nolog-test",
            "active": True,
            "working_set": ["src/*.py"],
            "reference": [],
            "signatures": [],
            "visible": [],
        }
        scope_file = tmp_path / ".consurg.yaml"
        scope_file.write_text(yaml.dump(scope_data))

        input_data = {
            "tool_name": "Read",
            "tool_input": {"file_path": "secret.txt"},
            "cwd": str(tmp_path),
        }

        env = {k: v for k, v in os.environ.items() if k != "CONSURG_LOG"}
        subprocess.run(
            [sys.executable, str(hook_path)],
            input=json.dumps(input_data),
            capture_output=True,
            text=True,
            env=env,
        )

        log_file = tmp_path / ".consurg-violations.log"
        assert not log_file.exists()
