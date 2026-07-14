import sys

import yaml
from typer.testing import CliRunner

from consurg.cli import app

runner = CliRunner()


def _project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "auth.py").write_text(
        "def login(user):\n    return True\n", encoding="utf-8"
    )
    (tmp_path / "src" / "types.py").write_text(
        "class User:\n    name: str\n", encoding="utf-8"
    )
    (tmp_path / "src" / "db.py").write_text("SECRET = 'x'\n", encoding="utf-8")
    (tmp_path / ".consurg.yaml").write_text(
        yaml.dump(
            {
                "version": 1,
                "scope": "demo",
                "active": True,
                "working_set": ["src/auth.py"],
                "signatures": ["src/types.py"],
            }
        ),
        encoding="utf-8",
    )
    return tmp_path


def test_copy_renders_scope(tmp_path, monkeypatch):
    _project(tmp_path, monkeypatch)
    result = runner.invoke(app, ["copy"])
    assert result.exit_code == 0, result.output
    assert "## FILE: src/auth.py (read-write)" in result.output
    assert "def login(user):" in result.output
    assert "## SIGNATURES: src/types.py" in result.output
    # Implementation of signature-tier and blocked files never leaks
    assert "SECRET" not in result.output


def test_copy_xml_format(tmp_path, monkeypatch):
    _project(tmp_path, monkeypatch)
    result = runner.invoke(app, ["copy", "--format", "xml", "--task", "do the thing"])
    assert result.exit_code == 0, result.output
    assert '<file path="src/auth.py"' in result.output
    assert "<task>do the thing</task>" in result.output


def test_copy_without_scope_fails(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["copy"])
    assert result.exit_code == 1
    assert "No scope defined" in result.output


def test_copy_rejects_unknown_format(tmp_path, monkeypatch):
    _project(tmp_path, monkeypatch)
    result = runner.invoke(app, ["copy", "--format", "docx"])
    assert result.exit_code == 1
    assert "Unknown format" in result.output


def test_run_without_scope_fails(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["run", "python", "-c", "pass"])
    assert result.exit_code == 1
    assert "No scope defined" in result.output


def test_run_executes_command_with_guard_env(tmp_path, monkeypatch):
    _project(tmp_path, monkeypatch)
    marker = tmp_path / "ran.txt"
    code = (
        "import os, pathlib; "
        "pathlib.Path(r'%s').write_text("
        "os.environ.get('CONSURG_GUARD_PORT', '') + '|' + os.environ.get('CONSURG_ACTIVE', ''))"
    ) % str(marker)

    result = runner.invoke(app, ["run", sys.executable, "-c", code])
    assert result.exit_code == 0, result.output

    port, active = marker.read_text().split("|")
    assert port.isdigit()
    assert active == "1"
    # Guard lockfile is cleaned up after the run
    assert not (tmp_path / ".consurg-guard.lock").exists()


def test_run_propagates_exit_code(tmp_path, monkeypatch):
    _project(tmp_path, monkeypatch)
    result = runner.invoke(app, ["run", sys.executable, "-c", "raise SystemExit(7)"])
    assert result.exit_code == 7


def test_run_missing_command(tmp_path, monkeypatch):
    _project(tmp_path, monkeypatch)
    result = runner.invoke(app, ["run", "definitely-not-a-real-tool-xyz"])
    assert result.exit_code == 1
    assert "Command not found" in result.output
