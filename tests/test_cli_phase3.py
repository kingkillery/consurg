import subprocess

import pytest
import yaml
from typer.testing import CliRunner

from consurg.cli import app

runner = CliRunner()


@pytest.fixture
def in_tmp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_trace_python_files(in_tmp):
    (in_tmp / "main.py").write_text("from utils import helper")
    (in_tmp / "utils.py").write_text("def helper(): pass")
    result = runner.invoke(app, ["trace", "main.py"])
    assert result.exit_code == 0
    assert "main.py" in result.output


def test_trace_with_apply(in_tmp):
    (in_tmp / "main.py").write_text("x = 1")
    result = runner.invoke(app, ["trace", "main.py", "--apply"])
    assert result.exit_code == 0
    assert (in_tmp / ".consurg.yaml").exists()
    data = yaml.safe_load((in_tmp / ".consurg.yaml").read_text())
    assert "main.py" in data["working_set"]


def test_trace_depth_limit(in_tmp):
    (in_tmp / "a.py").write_text("import b")
    (in_tmp / "b.py").write_text("import c")
    (in_tmp / "c.py").write_text("import d")
    (in_tmp / "d.py").write_text("x = 1")
    result = runner.invoke(app, ["trace", "a.py", "--depth", "1"])
    assert result.exit_code == 0


def test_trace_missing_entry_file(in_tmp):
    result = runner.invoke(app, ["trace", "nonexistent.py"])
    assert result.exit_code == 1
    assert "not found" in result.output.lower()


def test_trace_multiple_entries(in_tmp):
    (in_tmp / "app.py").write_text("import helpers")
    (in_tmp / "helpers.py").write_text("x = 1")
    (in_tmp / "cli.py").write_text("import helpers")
    result = runner.invoke(app, ["trace", "app.py", "cli.py"])
    assert result.exit_code == 0
    assert "app.py" in result.output
    assert "cli.py" in result.output


def test_git_diff_no_repo(in_tmp):
    result = runner.invoke(app, ["git-diff"])
    assert result.exit_code != 0 or "error" in result.output.lower()


def test_git_diff_with_repo(in_tmp):
    subprocess.run(["git", "init", "-b", "main"], cwd=str(in_tmp), capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(in_tmp), capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(in_tmp), capture_output=True)
    (in_tmp / "main.py").write_text("x = 1")
    subprocess.run(["git", "add", "."], cwd=str(in_tmp), capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(in_tmp), capture_output=True)
    subprocess.run(["git", "checkout", "-b", "feature"], cwd=str(in_tmp), capture_output=True)
    (in_tmp / "new.py").write_text("y = 2")
    subprocess.run(["git", "add", "."], cwd=str(in_tmp), capture_output=True)
    subprocess.run(["git", "commit", "-m", "add new"], cwd=str(in_tmp), capture_output=True)
    result = runner.invoke(app, ["git-diff", "main"])
    assert result.exit_code == 0


def test_git_diff_with_apply(in_tmp):
    subprocess.run(["git", "init", "-b", "main"], cwd=str(in_tmp), capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(in_tmp), capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(in_tmp), capture_output=True)
    (in_tmp / "main.py").write_text("x = 1")
    subprocess.run(["git", "add", "."], cwd=str(in_tmp), capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(in_tmp), capture_output=True)
    subprocess.run(["git", "checkout", "-b", "feature"], cwd=str(in_tmp), capture_output=True)
    (in_tmp / "new.py").write_text("y = 2")
    subprocess.run(["git", "add", "."], cwd=str(in_tmp), capture_output=True)
    subprocess.run(["git", "commit", "-m", "add new"], cwd=str(in_tmp), capture_output=True)
    result = runner.invoke(app, ["git-diff", "main", "--apply"])
    assert result.exit_code == 0
    assert (in_tmp / ".consurg.yaml").exists()
