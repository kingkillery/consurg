import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

HOOK_SCRIPT = str(Path(__file__).resolve().parent.parent / "hooks" / "enforce.py")


def _run_hook(tmp_path: Path, tool_name: str, tool_input: dict, scope_data: dict | None = None):
    if scope_data is not None:
        (tmp_path / ".consurg.yaml").write_text(yaml.dump(scope_data))

    stdin_data = json.dumps({
        "tool_name": tool_name,
        "tool_input": tool_input,
        "cwd": str(tmp_path),
    })

    result = subprocess.run(
        [sys.executable, HOOK_SCRIPT],
        input=stdin_data,
        capture_output=True,
        text=True,
    )
    return result


def test_no_scope_allows(tmp_path):
    result = _run_hook(tmp_path, "Read", {"file_path": "anything.py"})
    assert result.returncode == 0


def test_inactive_scope_allows(tmp_path):
    scope = {"version": 1, "active": False, "scope": "test", "working_set": []}
    result = _run_hook(tmp_path, "Read", {"file_path": "blocked.py"}, scope)
    assert result.returncode == 0


def test_blocked_file_read_denied(tmp_path):
    scope = {
        "version": 1, "active": True, "scope": "test",
        "working_set": ["src/*.py"], "reference": [], "signatures": [], "visible": [],
    }
    result = _run_hook(tmp_path, "Read", {"file_path": "other/secret.py"}, scope)
    assert result.returncode == 2
    stderr_data = json.loads(result.stderr)
    assert stderr_data["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_working_set_read_allowed(tmp_path):
    scope = {
        "version": 1, "active": True, "scope": "test",
        "working_set": ["src/*.py"], "reference": [], "signatures": [], "visible": [],
    }
    result = _run_hook(tmp_path, "Read", {"file_path": "src/main.py"}, scope)
    assert result.returncode == 0


def test_reference_read_allowed(tmp_path):
    scope = {
        "version": 1, "active": True, "scope": "test",
        "working_set": [], "reference": ["docs/*.md"], "signatures": [], "visible": [],
    }
    result = _run_hook(tmp_path, "Read", {"file_path": "docs/readme.md"}, scope)
    assert result.returncode == 0


def test_reference_write_blocked(tmp_path):
    scope = {
        "version": 1, "active": True, "scope": "test",
        "working_set": [], "reference": ["docs/*.md"], "signatures": [], "visible": [],
    }
    result = _run_hook(tmp_path, "Edit", {"file_path": "docs/readme.md"}, scope)
    assert result.returncode == 2


def test_working_set_write_allowed(tmp_path):
    scope = {
        "version": 1, "active": True, "scope": "test",
        "working_set": ["src/*.py"], "reference": [], "signatures": [], "visible": [],
    }
    result = _run_hook(tmp_path, "Write", {"file_path": "src/main.py"}, scope)
    assert result.returncode == 0


def test_unknown_tool_allowed(tmp_path):
    scope = {
        "version": 1, "active": True, "scope": "test",
        "working_set": [], "reference": [], "signatures": [], "visible": [],
    }
    result = _run_hook(tmp_path, "Bash", {"command": "ls"}, scope)
    assert result.returncode == 0
