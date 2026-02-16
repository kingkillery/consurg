from consurg.file_context_ui import (
    BINARY_FILE_PLACEHOLDER,
    FileContextUIConfig,
    LARGE_FILE_PLACEHOLDER,
    compose_prompt,
    is_denied,
    start_ui_server,
    load_file_context_ui_config,
)


def test_denylist_matching():
    patterns = [".git", "node_modules", "__pycache__", "*.pyc", "dist", "docs/private/*.md", "**/secret/**"]
    assert is_denied(".git/config", patterns)
    assert is_denied("node_modules/pkg/index.js", patterns)
    assert is_denied("__pycache__/x.pyc", patterns)
    assert is_denied("foo/bar.pyc", patterns)
    assert is_denied("docs/private/notes.md", patterns)
    assert is_denied("workspace/secret/file.txt", patterns)
    assert not is_denied("src/main.py", patterns)


def test_compose_prompt_path_safety(tmp_path):
    cwd = tmp_path
    outside = tmp_path.parent / "outside-root.txt"
    outside.write_text("outside", encoding="utf-8")

    allowed = cwd / "allowed.py"
    allowed.write_text("print('ok')", encoding="utf-8")
    allowed_rel = "allowed.py"

    config = load_file_context_ui_config(cwd)
    output = compose_prompt([allowed_rel, "../outside-root.txt"], cwd, config, format="markdown")
    assert "outside-root.txt" not in output
    assert "## FILE: allowed.py" in output


def test_compose_prompt_limits_and_binary_detection(tmp_path):
    cwd = tmp_path
    good = cwd / "good.txt"
    good.write_text("short", encoding="utf-8")
    large = cwd / "large.txt"
    large.write_text("x" * 64, encoding="utf-8")
    binary = cwd / "binary.bin"
    binary.write_bytes(b"a\x00b")

    config = FileContextUIConfig(
        never_include=[],
        max_file_bytes=10,
        max_total_bytes=200,
        hide_excluded=False,
    )

    output = compose_prompt(["good.txt", "binary.bin", "large.txt"], cwd, config, format="markdown")
    assert "## FILE: good.txt" in output
    assert BINARY_FILE_PLACEHOLDER in output
    assert LARGE_FILE_PLACEHOLDER in output

    trunc_cfg = FileContextUIConfig(
        never_include=[],
        max_file_bytes=1024,
        max_total_bytes=32,
        hide_excluded=False,
    )
    out2 = compose_prompt(["good.txt", "large.txt"], cwd, trunc_cfg, format="markdown")
    assert "TRUNCATED: total size limit reached" in out2


def test_compose_prompt_can_include_readme(tmp_path):
    cwd = tmp_path
    readme = cwd / "README.md"
    readme.write_text("# Consurg", encoding="utf-8")

    config = load_file_context_ui_config(cwd)
    output = compose_prompt(["README.md"], cwd, config, format="markdown")

    assert "## FILE: README.md" in output
    assert "# Consurg" in output


def test_start_ui_server_launches_browser_and_exits(tmp_path, monkeypatch):
    cwd = tmp_path
    (cwd / "README.md").write_text("# Consurg", encoding="utf-8")

    config = load_file_context_ui_config(cwd)
    launched = {}

    def fake_open(url, new=1, autoraise=True):
        launched["url"] = url
        raise KeyboardInterrupt

    monkeypatch.setattr("consurg.file_context_ui.webbrowser.open", fake_open)
    start_ui_server(cwd, config, preselected=["README.md"])

    assert launched["url"].startswith("http://127.0.0.1:")
