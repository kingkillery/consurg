"""Tests for the wrap command — env vars, subprocess, cleanup."""

import json
import os
import sys
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from consurg.cli import app
from consurg.guard.lockfile import GuardLockfile


runner = CliRunner()


@pytest.fixture
def scope_dir(tmp_path, monkeypatch):
    """Create a temp directory with a valid .consurg.yaml and cd to it."""
    scope_data = {
        "version": 1,
        "scope": "test-wrap",
        "active": True,
        "working_set": ["src/*.py"],
        "reference": ["docs/*.md"],
        "signatures": [],
        "visible": [],
    }
    scope_file = tmp_path / ".consurg.yaml"
    scope_file.write_text(yaml.dump(scope_data))
    monkeypatch.chdir(tmp_path)
    return tmp_path


class TestWrapCommand:
    def test_wrap_no_command(self, scope_dir):
        result = runner.invoke(app, ["wrap"])
        assert result.exit_code != 0

    def test_wrap_sets_env_vars(self, scope_dir):
        """Wrap should set CONSURG_GUARD_PORT and CONSURG_ACTIVE."""
        out_file = scope_dir / "_env_output.txt"
        script = (
            f'import os; '
            f'from pathlib import Path; '
            f'Path({str(out_file)!r}).write_text('
            f'os.environ.get("CONSURG_GUARD_PORT","") + "\\n" + '
            f'os.environ.get("CONSURG_ACTIVE",""))'
        )
        result = runner.invoke(app, ["wrap", "--", sys.executable, "-c", script])
        assert out_file.exists(), f"Script did not write output file. exit={result.exit_code}"
        lines = out_file.read_text().strip().splitlines()
        assert len(lines) == 2
        assert lines[0].isdigit(), f"Expected port number, got: {lines[0]}"
        assert lines[1] == "1"

    def test_wrap_cleans_up_lockfile(self, scope_dir):
        """After wrap completes, lockfile should be removed."""
        result = runner.invoke(app, ["wrap", "--", sys.executable, "-c", "pass"])
        lockfile = scope_dir / ".consurg-guard.lock"
        assert not lockfile.exists()

    def test_wrap_passes_exit_code(self, scope_dir):
        """Wrap should propagate the subprocess exit code."""
        result = runner.invoke(app, ["wrap", "--", sys.executable, "-c", "import sys; sys.exit(42)"])
        assert result.exit_code == 42

    def test_wrap_no_scope(self, tmp_path, monkeypatch):
        """Wrap without scope should fail."""
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["wrap", "--", "echo", "hello"])
        assert result.exit_code != 0
        assert "No scope" in result.output


class TestWrapLockfile:
    def test_lockfile_written_during_wrap(self, scope_dir):
        """During wrap execution, a lockfile should exist with correct port."""
        out_file = scope_dir / "_lock_output.txt"
        script = (
            f'import json; '
            f'from pathlib import Path; '
            f'data = json.loads(Path(".consurg-guard.lock").read_text()); '
            f'ok = "port" in data and "pid" in data; '
            f'Path({str(out_file)!r}).write_text("OK" if ok else "FAIL")'
        )
        result = runner.invoke(app, ["wrap", "--", sys.executable, "-c", script])
        assert out_file.exists(), f"Script did not write output file. exit={result.exit_code}"
        assert out_file.read_text().strip() == "OK"
