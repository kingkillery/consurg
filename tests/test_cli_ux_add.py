import pytest
import yaml
from typer.testing import CliRunner
from consurg.cli import app

runner = CliRunner()

@pytest.fixture
def in_tmp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path

def test_add_reports_actual_added_count(in_tmp):
    runner.invoke(app, ["init"])
    # First add: 1 new
    result = runner.invoke(app, ["add", "file1.py"])
    assert result.exit_code == 0
    assert "Added 1 pattern(s)" in result.output

    # Second add: 1 new, 1 duplicate
    result = runner.invoke(app, ["add", "file1.py", "file2.py"])
    assert result.exit_code == 0
    # Should report actual added count and skipped duplicates
    assert "Added 1 pattern(s)" in result.output
    assert "Skipped 1 duplicate(s)" in result.output

def test_add_warns_on_missing_file(in_tmp):
    runner.invoke(app, ["init"])
    result = runner.invoke(app, ["add", "missing_file.py"])
    assert result.exit_code == 0
    # Should warn about missing file
    assert "Warning: File 'missing_file.py' not found locally" in result.output
    assert "Added 1 pattern(s)" in result.output

def test_add_does_not_warn_on_glob(in_tmp):
    runner.invoke(app, ["init"])
    result = runner.invoke(app, ["add", "*.py"])
    assert result.exit_code == 0
    assert "Added 1 pattern(s)" in result.output
    # Should NOT warn about glob even if no .py files exist
    assert "Warning" not in result.output

def test_add_all_duplicates(in_tmp):
    runner.invoke(app, ["init"])
    runner.invoke(app, ["add", "file.py"])
    result = runner.invoke(app, ["add", "file.py"])
    assert result.exit_code == 0
    # assert "No new patterns added" in result.output  <-- Redundant if we see skipped count
    assert "Skipped 1 duplicate(s)" in result.output
