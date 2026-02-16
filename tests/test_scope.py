from pathlib import Path

import pytest
import yaml

from consurg.scope import Scope, ScopeError, load_scope, pattern_matches


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


class TestPatternMatches:
    # --- Regression: existing behavior preserved ---

    def test_exact_match(self):
        assert pattern_matches("src/main.py", "src/main.py")

    def test_star_glob(self):
        assert pattern_matches("utils.py", "*.py")

    def test_double_star_glob(self):
        assert pattern_matches("deep/nested/module.py", "**/*.py")

    def test_backslash_normalization(self):
        assert pattern_matches("src\\main.py", "src/main.py")
        assert pattern_matches("src/main.py", "src\\main.py")

    def test_no_match(self):
        assert not pattern_matches("src/main.py", "docs/*.md")

    # --- New: component-level matching ---

    def test_extension_glob_matches_nested(self):
        assert pattern_matches("foo/bar.pyc", "*.pyc")

    def test_extension_glob_matches_deep_nested(self):
        assert pattern_matches("a/b/c/file.pyc", "*.pyc")

    def test_extension_glob_matches_top_level(self):
        assert pattern_matches("file.pyc", "*.pyc")

    # --- New: bare directory names ---

    def test_bare_dir_git(self):
        assert pattern_matches(".git/config", ".git")

    def test_bare_dir_pycache(self):
        assert pattern_matches("src/__pycache__/module.cpython-311.pyc", "__pycache__")

    def test_bare_dir_node_modules(self):
        assert pattern_matches("node_modules/express/index.js", "node_modules")

    def test_bare_dir_venv(self):
        assert pattern_matches("venv/lib/python3.11/site.py", "venv")

    def test_bare_dir_no_false_positive(self):
        assert not pattern_matches("src-extra/file.py", "src")

    # --- New: path-as-prefix matching ---

    def test_path_prefix_matches_children(self):
        assert pattern_matches("src/lib/utils.py", "src/lib")

    def test_path_prefix_with_glob(self):
        assert pattern_matches("docs/api/ref.md", "docs/api")

    # --- Edge cases ---

    def test_empty_path_returns_false(self):
        assert not pattern_matches("", "*.py")

    def test_empty_pattern_returns_false(self):
        assert not pattern_matches("src/main.py", "")

    def test_leading_dot_slash_stripped(self):
        assert pattern_matches("./src/main.py", "src/main.py")
        assert pattern_matches("src/main.py", "./src/main.py")

    def test_both_empty_returns_false(self):
        assert not pattern_matches("", "")
