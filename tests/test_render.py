from pathlib import Path
from xml.etree import ElementTree

import pytest

import yaml

import consurg.render as render

from consurg.file_context_ui import initial_tiers, save_scope_tiers
from consurg.render import (
    RenderLimits,
    compose_from_scope,
    compose_from_tiers,
    estimate_tokens,
    safe_read_context_file,
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
    ampersand_file = cwd / "src" / "terms&conditions.py"
    ampersand_file.write_text("VALUE = 'quoted'\n", encoding="utf-8")
    result = compose_from_tiers(
        {"src/auth.py": 3, "src/types.py": 2, "src/terms&conditions.py": 1},
        cwd,
        fmt="xml",
        task="review <this>",
        scope_name='scope "quoted"',
    )
    root = ElementTree.fromstring(result.text)
    assert root.tag == "context"
    assert root.attrib["name"] == 'scope "quoted"'
    assert root.findtext("task") == "review <this>"
    assert root.find('.//file[@path="src/terms&conditions.py"]') is not None
    assert '<file path="src/auth.py" access="read-only">' in result.text
    assert '<signatures path="src/types.py"' in result.text


def test_compose_rejects_paths_and_symlinks_outside_root(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    cwd = _project(project)
    outside = tmp_path / "outside.py"
    outside.write_text("DO_NOT_LEAK = True\n", encoding="utf-8")

    traversal = compose_from_tiers({"../outside.py": 3}, cwd)
    assert "DO_NOT_LEAK" not in traversal.text
    assert ("../outside.py", "outside project root") in traversal.skipped

    link = cwd / "src" / "outside-link.py"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks are unavailable on this platform")
    linked = compose_from_tiers({"src/outside-link.py": 3}, cwd)
    assert "DO_NOT_LEAK" not in linked.text
    assert ("src/outside-link.py", "outside project root") in linked.skipped


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


def test_signature_tier_respects_max_file_bytes(tmp_path):
    cwd = _project(tmp_path)
    source = cwd / "src" / "large.py"
    source.write_text("def hidden():\n    pass\n" + "# x\n" * 100, encoding="utf-8")

    result = compose_from_tiers(
        {"src/large.py": 2}, cwd, limits=RenderLimits(max_file_bytes=20)
    )

    assert ("src/large.py", "exceeds max_file_bytes") in result.skipped
    assert "def hidden" not in result.text


def test_safe_reader_rejects_nul_beyond_initial_chunk(tmp_path):
    cwd = _project(tmp_path)
    target = cwd / "src" / "late-nul.txt"
    target.write_bytes(b"x" * 9000 + b"\x00after")

    content, reason = safe_read_context_file(target, cwd, 10000)

    assert content is None
    assert reason == "binary file"


def test_xml_render_sanitizes_forbidden_control_characters(tmp_path):
    cwd = _project(tmp_path)
    (cwd / "src" / "control.py").write_text("value = '\\x01'\n", encoding="utf-8")

    result = compose_from_tiers(
        {"src/control.py": 3},
        cwd,
        fmt="xml",
        scope_name="scope\x01name",
        reason="reason\x0btext",
        task="task\x02text",
    )

    root = ElementTree.fromstring(result.text)
    assert root.attrib["name"] == "scopename"
    assert root.findtext("reason") == "reasontext"
    assert root.findtext("task") == "tasktext"
    assert "\x01" not in result.text


def test_safe_reader_rejects_symlink_component_inside_project(tmp_path):
    cwd = _project(tmp_path)
    target = cwd / "src" / "auth.py"
    link = cwd / "src" / "inside-link.py"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlinks are unavailable on this platform")

    content, reason = safe_read_context_file(link, cwd, 20000)

    assert content is None
    assert reason == "symlink or reparse point"


def test_safe_reader_omits_file_when_path_changes_after_open(tmp_path, monkeypatch):
    cwd = _project(tmp_path)
    target = cwd / "src" / "swap.py"
    replacement = cwd / "src" / "replacement.py"
    target.write_text("SECRET = 'original'\n", encoding="utf-8")
    replacement.write_text("SECRET = 'replacement'\n", encoding="utf-8")
    original_snapshot = render._path_component_identities
    calls = 0

    def swap_before_second_snapshot(root, relative):
        nonlocal calls
        calls += 1
        if calls == 2:
            try:
                target.unlink()
                replacement.replace(target)
            except OSError:
                pytest.skip("open-file replacement is unavailable on this platform")
        return original_snapshot(root, relative)

    monkeypatch.setattr(render, "_path_component_identities", swap_before_second_snapshot)
    content, reason = safe_read_context_file(target, cwd, 20000)

    assert content is None
    assert reason == "path changed during read"
