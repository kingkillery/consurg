from pathlib import Path

import yaml

from consurg.file_context_ui import initial_tiers, save_scope_tiers
from consurg.render import (
    RenderLimits,
    compose_from_scope,
    compose_from_tiers,
    estimate_tokens,
)
from consurg.scope import Scope


def _project(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "auth.py").write_text(
        "def login(user, password):\n    return True\n", encoding="utf-8"
    )
    (tmp_path / "src" / "types.py").write_text(
        "class User:\n    name: str\n\ndef make_user(name):\n    return User()\n",
        encoding="utf-8",
    )
    (tmp_path / "src" / "db.py").write_text("SECRET = 'x'\n", encoding="utf-8")
    (tmp_path / "config.yaml").write_text("key: value\n", encoding="utf-8")
    return tmp_path


def test_compose_from_tiers_full_and_signatures(tmp_path):
    cwd = _project(tmp_path)
    tiers = {
        "src/auth.py": 4,
        "config.yaml": 3,
        "src/types.py": 2,
        "src/db.py": 1,
    }
    result = compose_from_tiers(tiers, cwd, scope_name="demo")

    # T4/T3: full content
    assert "## FILE: src/auth.py (read-write)" in result.text
    assert "def login(user, password):" in result.text
    assert "## FILE: config.yaml (read-only)" in result.text
    assert "key: value" in result.text

    # T2: signatures only, no implementation
    assert "## SIGNATURES: src/types.py" in result.text
    assert "class User:" in result.text
    assert "def make_user(name):" in result.text
    assert "return User()" not in result.text

    # T1: tree listing only, no content
    assert "src/db.py" in result.text
    assert "SECRET" not in result.text

    assert result.token_estimate == estimate_tokens(result.text)
    assert ("src/auth.py", 4) in result.included
    assert ("src/db.py", 1) in result.included


def test_compose_from_tiers_respects_limits_and_denylist(tmp_path):
    cwd = _project(tmp_path)
    (cwd / "big.txt").write_text("x" * 500, encoding="utf-8")
    limits = RenderLimits(never_include=["config.yaml"], max_file_bytes=100)

    result = compose_from_tiers(
        {"big.txt": 4, "config.yaml": 4, "src/auth.py": 4}, cwd, limits=limits
    )
    skipped_paths = {p for p, _ in result.skipped}
    assert "big.txt" in skipped_paths
    assert "config.yaml" in skipped_paths
    assert "## FILE: src/auth.py" in result.text
    assert "## Omitted" in result.text


def test_compose_from_tiers_xml_format(tmp_path):
    cwd = _project(tmp_path)
    result = compose_from_tiers(
        {"src/auth.py": 3, "src/types.py": 2}, cwd, fmt="xml", task="review this"
    )
    assert '<file path="src/auth.py" access="read-only">' in result.text
    assert '<signatures path="src/types.py"' in result.text
    assert "<task>review this</task>" in result.text


def test_compose_from_scope_resolves_tiers(tmp_path):
    cwd = _project(tmp_path)
    scope = Scope(
        scope_name="auth-work",
        working_set=["src/auth.py"],
        reference=["config.yaml"],
        signatures=["src/types.py"],
    )
    candidates = ["src/auth.py", "src/types.py", "src/db.py", "config.yaml"]
    result = compose_from_scope(scope, cwd, candidates)

    assert "## FILE: src/auth.py (read-write)" in result.text
    assert "## SIGNATURES: src/types.py" in result.text
    # db.py is unlisted -> tier 0 -> fully omitted
    assert "src/db.py" not in result.text


def test_save_scope_tiers_roundtrip(tmp_path):
    cwd = _project(tmp_path)
    save_scope_tiers(
        cwd,
        {"src/auth.py": 4, "config.yaml": 3, "src/types.py": 2},
        scope_name="picked",
    )

    data = yaml.safe_load((cwd / ".consurg.yaml").read_text(encoding="utf-8"))
    assert data["scope"] == "picked"
    assert data["working_set"] == ["src/auth.py"]
    assert data["reference"] == ["config.yaml"]
    assert data["signatures"] == ["src/types.py"]
    assert data["active"] is True

    # initial_tiers resolves the saved scope back onto candidates
    tiers, name = initial_tiers(
        cwd, ["src/auth.py", "config.yaml", "src/types.py", "src/db.py"]
    )
    assert name == "picked"
    assert tiers["src/auth.py"] == 4
    assert tiers["config.yaml"] == 3
    assert tiers["src/types.py"] == 2
    assert tiers["src/db.py"] == 0


def test_save_scope_tiers_preserves_other_keys(tmp_path):
    cwd = _project(tmp_path)
    (cwd / ".consurg.yaml").write_text(
        yaml.dump(
            {
                "version": 1,
                "scope": "existing",
                "active": False,
                "reason": "why not",
                "working_set": ["old.py"],
                "visible": ["src/**"],
                "file_context_ui": {"max_file_bytes": 12345},
            }
        ),
        encoding="utf-8",
    )
    save_scope_tiers(cwd, {"src/auth.py": 4})

    data = yaml.safe_load((cwd / ".consurg.yaml").read_text(encoding="utf-8"))
    assert data["working_set"] == ["src/auth.py"]
    assert data["scope"] == "existing"
    assert data["reason"] == "why not"
    assert data["visible"] == ["src/**"]
    assert data["file_context_ui"] == {"max_file_bytes": 12345}
