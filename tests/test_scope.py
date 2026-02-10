from pathlib import Path

import pytest
import yaml

from consurg.scope import Scope, ScopeError, load_scope


def _write_scope(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / ".consurg.yaml"
    p.write_text(yaml.dump(data))
    return p


def test_load_valid_scope(tmp_path):
    p = _write_scope(tmp_path, {
        "version": 1,
        "scope": "test-scope",
        "active": True,
        "working_set": ["src/*.py"],
        "reference": ["docs/*.md"],
    })
    scope = load_scope(p)
    assert scope is not None
    assert scope.version == 1
    assert scope.scope_name == "test-scope"
    assert scope.active is True
    assert scope.working_set == ["src/*.py"]
    assert scope.reference == ["docs/*.md"]
    assert scope.signatures == []
    assert scope.visible == []
    assert scope.dynamic_deps == []


def test_load_missing_file_returns_none(tmp_path):
    result = load_scope(tmp_path / "nonexistent.yaml")
    assert result is None


def test_invalid_version_raises(tmp_path):
    p = _write_scope(tmp_path, {"version": 99, "active": True})
    with pytest.raises(ScopeError, match="Unsupported scope version"):
        load_scope(p)


def test_invalid_active_type_raises(tmp_path):
    p = _write_scope(tmp_path, {"version": 1, "active": "yes"})
    with pytest.raises(ScopeError, match="must be a boolean"):
        load_scope(p)
