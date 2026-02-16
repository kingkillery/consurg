from pathlib import Path

import pytest
import yaml

from consurg.scope import (
    NetworkPolicy,
    SandboxConfig,
    Scope,
    ScopeError,
    load_scope,
    pattern_matches,
)


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


# --- Schema v2: SandboxConfig + NetworkPolicy ---


class TestSandboxDataclasses:
    def test_network_policy_defaults(self):
        np = NetworkPolicy()
        assert np.policy == "unrestricted"
        assert np.allow == []
        assert np.deny == []

    def test_sandbox_config_defaults(self):
        sc = SandboxConfig()
        assert sc.backend == "none"
        assert sc.autonomy == 2
        assert isinstance(sc.network, NetworkPolicy)
        assert sc.command_deny == []

    def test_scope_has_sandbox_default(self):
        scope = Scope()
        assert isinstance(scope.sandbox, SandboxConfig)
        assert scope.sandbox.backend == "none"


class TestLoadScopeV2:
    def test_load_scope_v2_full(self, tmp_path):
        p = _write_scope(tmp_path, {
            "version": 2,
            "scope": "auth-refactor",
            "active": True,
            "working_set": ["src/auth/*.py"],
            "reference": ["src/core/*.py"],
            "sandbox": {
                "backend": "docker",
                "autonomy": 1,
                "network": {
                    "policy": "allowlist",
                    "allow": ["api.github.com", "pypi.org"],
                },
                "commands": {
                    "deny": ["rm -rf *", "git push --force"],
                },
            },
        })
        scope = load_scope(p)
        assert scope is not None
        assert scope.version == 2
        assert scope.scope_name == "auth-refactor"
        assert scope.working_set == ["src/auth/*.py"]
        assert scope.sandbox.backend == "docker"
        assert scope.sandbox.autonomy == 1
        assert scope.sandbox.network.policy == "allowlist"
        assert scope.sandbox.network.allow == ["api.github.com", "pypi.org"]
        assert scope.sandbox.network.deny == []
        assert scope.sandbox.command_deny == ["rm -rf *", "git push --force"]

    def test_load_scope_v2_minimal(self, tmp_path):
        """v2 with no sandbox section gets all defaults."""
        p = _write_scope(tmp_path, {
            "version": 2,
            "scope": "minimal-v2",
            "active": True,
        })
        scope = load_scope(p)
        assert scope is not None
        assert scope.version == 2
        assert scope.sandbox.backend == "none"
        assert scope.sandbox.autonomy == 2
        assert scope.sandbox.network.policy == "unrestricted"
        assert scope.sandbox.command_deny == []

    def test_load_scope_v1_gets_default_sandbox(self, tmp_path):
        """v1 scopes still load and get a default SandboxConfig."""
        p = _write_scope(tmp_path, {
            "version": 1,
            "scope": "legacy",
            "active": True,
            "working_set": ["src/*.py"],
        })
        scope = load_scope(p)
        assert scope is not None
        assert scope.version == 1
        assert scope.sandbox.backend == "none"
        assert scope.sandbox.autonomy == 2

    def test_load_scope_v2_network_denylist(self, tmp_path):
        p = _write_scope(tmp_path, {
            "version": 2,
            "scope": "restricted",
            "active": True,
            "sandbox": {
                "network": {
                    "policy": "denylist",
                    "deny": ["evil.com", "*.malware.net"],
                },
            },
        })
        scope = load_scope(p)
        assert scope.sandbox.network.policy == "denylist"
        assert scope.sandbox.network.deny == ["evil.com", "*.malware.net"]
        assert scope.sandbox.network.allow == []

    def test_invalid_version_still_raises(self, tmp_path):
        p = _write_scope(tmp_path, {"version": 99, "active": True})
        with pytest.raises(ScopeError, match="Unsupported scope version"):
            load_scope(p)
