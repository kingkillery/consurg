import pytest
from typer.testing import CliRunner
from consurg.cli import app

runner = CliRunner()

@pytest.fixture
def in_tmp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path

def test_add_warns_non_existent(in_tmp):
    runner.invoke(app, ["init"])
    result = runner.invoke(app, ["add", "non_existent.py"])
    assert result.exit_code == 0
    assert "File or directory 'non_existent.py' not found" in result.output

def test_add_warns_no_match_wildcard(in_tmp):
    runner.invoke(app, ["init"])
    result = runner.invoke(app, ["add", "*.foo"])
    assert result.exit_code == 0
    assert "Pattern '*.foo' matches no files" in result.output

def test_add_warns_directory(in_tmp):
    runner.invoke(app, ["init"])
    (in_tmp / "subdir").mkdir()
    result = runner.invoke(app, ["add", "subdir"])
    assert result.exit_code == 0
    assert "Directory added" in result.output
    # Check for suggestion, allowing for line wrapping
    assert "subdir/*" in result.output

def test_add_success_wildcard(in_tmp):
    runner.invoke(app, ["init"])
    (in_tmp / "test.py").touch()
    result = runner.invoke(app, ["add", "*.py"])
    assert result.exit_code == 0
    assert "matches no files" not in result.output
    assert "Added 1 pattern(s)" in result.output

def test_add_success_literal(in_tmp):
    runner.invoke(app, ["init"])
    (in_tmp / "test.py").touch()
    result = runner.invoke(app, ["add", "test.py"])
    assert result.exit_code == 0
    assert "not found" not in result.output
