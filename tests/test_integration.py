import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from consurg.cli import app
from consurg.enforce import resolve_tier
from consurg.scope import load_scope

runner = CliRunner()
HOOK_SCRIPT = str(Path(__file__).resolve().parent.parent / "hooks" / "enforce.py")


@pytest.fixture
def in_tmp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _run_hook(tmp_path: Path, tool_name: str, tool_input: dict):
    stdin_data = json.dumps({
        "tool_name": tool_name,
        "tool_input": tool_input,
        "cwd": str(tmp_path),
    })
    return subprocess.run(
        [sys.executable, HOOK_SCRIPT],
        input=stdin_data,
        capture_output=True,
        text=True,
    )


def test_init_creates_valid_scope(in_tmp):
    result = runner.invoke(app, ["init", "integration-test"])
    assert result.exit_code == 0
    scope = load_scope(in_tmp / ".consurg.yaml")
    assert scope is not None
    assert scope.scope_name == "integration-test"
    assert scope.active is True


def test_add_populates_working_set(in_tmp):
    runner.invoke(app, ["init"])
    runner.invoke(app, ["add", "src/*.py", "main.py"])
    data = yaml.safe_load((in_tmp / ".consurg.yaml").read_text())
    assert "src/*.py" in data["working_set"]
    assert "main.py" in data["working_set"]


def test_add_read_populates_reference(in_tmp):
    runner.invoke(app, ["init"])
    runner.invoke(app, ["add", "--read", "docs/*.md"])
    data = yaml.safe_load((in_tmp / ".consurg.yaml").read_text())
    assert "docs/*.md" in data["reference"]


def test_resolve_tier_correct(in_tmp):
    runner.invoke(app, ["init"])
    runner.invoke(app, ["add", "src/*.py"])
    runner.invoke(app, ["add", "--read", "docs/*.md"])
    scope = load_scope(in_tmp / ".consurg.yaml")
    assert resolve_tier("src/main.py", scope) == (4, "READ-WRITE")
    assert resolve_tier("docs/readme.md", scope) == (3, "READ-ONLY")
    assert resolve_tier("other.txt", scope) == (0, "BLOCKED")


def test_hook_blocks_read_tier0(in_tmp):
    runner.invoke(app, ["init"])
    runner.invoke(app, ["add", "src/*.py"])
    result = _run_hook(in_tmp, "Read", {"file_path": "secret/passwords.txt"})
    assert result.returncode == 2


def test_hook_allows_read_tier3(in_tmp):
    runner.invoke(app, ["init"])
    runner.invoke(app, ["add", "--read", "docs/*.md"])
    result = _run_hook(in_tmp, "Read", {"file_path": "docs/readme.md"})
    assert result.returncode == 0


def test_hook_blocks_write_tier3(in_tmp):
    runner.invoke(app, ["init"])
    runner.invoke(app, ["add", "--read", "docs/*.md"])
    result = _run_hook(in_tmp, "Write", {"file_path": "docs/readme.md"})
    assert result.returncode == 2


def test_status_runs(in_tmp):
    runner.invoke(app, ["init", "int-test"])
    runner.invoke(app, ["add", "src/*.py"])
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "int-test" in result.output


def test_map_runs(in_tmp):
    runner.invoke(app, ["init", "int-test"])
    (in_tmp / "src").mkdir()
    (in_tmp / "src" / "app.py").write_text("x = 1")
    runner.invoke(app, ["add", "src/*.py"])
    result = runner.invoke(app, ["map"])
    assert result.exit_code == 0
