import json
import os
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from xml.etree import ElementTree

import pytest

import yaml
import consurg.file_context_ui as file_context_ui


from consurg.file_context_ui import (
    BINARY_FILE_PLACEHOLDER,
    LARGE_FILE_PLACEHOLDER,
    FileContextUIConfig,
    _build_html,
    _make_request_handler,
    _sanitize_tiers,
    compose_prompt,
    is_denied,
    list_candidate_files,
    load_file_context_ui_config,
    start_ui_server,
    ScopeExpansionConfirmationRequired,
    save_scope_tiers,
)
from consurg.render import HARD_MAX_FILE_BYTES, HARD_MAX_TOTAL_BYTES


def test_denylist_matching():
    patterns = [
        ".git",
        "node_modules",
        "__pycache__",
        "*.pyc",
        "dist",
        "docs/private/*.md",
        "**/secret/**",
    ]
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
    output = compose_prompt(
        [allowed_rel, "../outside-root.txt"], cwd, config, format="markdown"
    )
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

    output = compose_prompt(
        ["good.txt", "binary.bin", "large.txt"], cwd, config, format="markdown"
    )
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


def test_legacy_xml_compose_is_valid_xml_1_0(tmp_path):
    (tmp_path / "control.txt").write_text("ok\x01 & <tag>", encoding="utf-8")
    config = FileContextUIConfig([], max_file_bytes=1000, max_total_bytes=1000, hide_excluded=False)

    output = compose_prompt(["control.txt"], tmp_path, config, format="xml")

    root = ElementTree.fromstring(output)
    assert root.tag == "context"
    assert root.find("file").text == "ok & <tag>"


def test_invalid_ui_config_falls_back_to_safe_defaults(tmp_path):
    (tmp_path / ".consurg.yaml").write_text("file_context_ui: [", encoding="utf-8")

    config = load_file_context_ui_config(tmp_path)

    assert ".git" in config.never_include
    assert config.max_file_bytes == 20000
    assert config.max_total_bytes == 200000

def test_ui_config_clamps_repository_controlled_size_limits(tmp_path):
    (tmp_path / ".consurg.yaml").write_text(
        "file_context_ui:\n  max_file_bytes: 999999999999\n  max_total_bytes: 999999999999\n",
        encoding="utf-8",
    )

    config = load_file_context_ui_config(tmp_path)

    assert config.max_file_bytes == HARD_MAX_FILE_BYTES
    assert config.max_total_bytes == HARD_MAX_TOTAL_BYTES



def test_candidate_listing_includes_untracked_files_but_not_internal_dirs(
    tmp_path, monkeypatch
):
    (tmp_path / "tracked.py").write_text("tracked", encoding="utf-8")
    (tmp_path / "new.py").write_text("new", encoding="utf-8")
    (tmp_path / ".llm-router").mkdir()
    (tmp_path / ".llm-router" / "trace.jsonl").write_text("private", encoding="utf-8")
    (tmp_path / "nested-repo").mkdir()

    monkeypatch.setattr(
        "consurg.file_context_ui.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=b"tracked.py\0new.py\0.llm-router/trace.jsonl\0nested-repo\0",
        ),
    )

    assert list_candidate_files(tmp_path) == ["new.py", "tracked.py"]


def test_candidate_listing_preserves_nul_delimited_legal_whitespace(tmp_path, monkeypatch):
    names = [" leading.py", "trailing .py"]
    if os.name != "nt":
        names.append("line\nbreak.py")
    for name in names:
        (tmp_path / name).write_text("ok", encoding="utf-8")

    monkeypatch.setattr(
        "consurg.file_context_ui.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0, stdout="\0".join(names).encode("utf-8") + b"\0"
        ),
    )

    assert list_candidate_files(tmp_path) == sorted(names)


def test_candidate_listing_fallback_prunes_dependency_directories(
    tmp_path, monkeypatch
):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('ok')", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "package.js").write_text("ignored", encoding="utf-8")

    def git_unavailable(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr("consurg.file_context_ui.subprocess.run", git_unavailable)

    assert list_candidate_files(tmp_path) == ["src/main.py"]


def test_sanitize_tiers_restricts_requests_to_visible_policy_allowed_files(tmp_path):
    (tmp_path / "safe.py").write_text("safe", encoding="utf-8")
    (tmp_path / "secret.env").write_text("secret", encoding="utf-8")
    outside = tmp_path.parent / "outside.py"
    outside.write_text("outside", encoding="utf-8")

    result = _sanitize_tiers(
        {
            "safe.py": 3,
            "secret.env": 4,
            "../outside.py": 4,
            "not-listed.py": 4,
            "off.py": 0,
        },
        tmp_path,
        allowed_paths={"safe.py", "secret.env"},
        deny_patterns=["*.env"],
    )

    assert result == {"safe.py": 3}


def test_scope_save_preserves_unchanged_wildcards_and_unmatched_entries(tmp_path):
    (tmp_path / "src").mkdir()
    for name in ("a.py", "b.py"):
        (tmp_path / "src" / name).write_text(name, encoding="utf-8")
    (tmp_path / ".consurg.yaml").write_text(
        "version: 1\nworking_set: ['src/*.py', 'missing.py']\n",
        encoding="utf-8",
    )
    candidates = ["src/a.py", "src/b.py"]
    save_scope_tiers(
        tmp_path,
        {path: 4 for path in candidates},
        candidates=candidates,
        previous_tiers={path: 4 for path in candidates},
    )

    saved = yaml.safe_load((tmp_path / ".consurg.yaml").read_text(encoding="utf-8"))
    assert saved["working_set"] == ["src/*.py", "missing.py"]


def test_scope_save_requires_confirmation_before_expanding_wildcard(tmp_path):
    (tmp_path / "src").mkdir()
    for name in ("a.py", "b.py"):
        (tmp_path / "src" / name).write_text(name, encoding="utf-8")
    (tmp_path / ".consurg.yaml").write_text(
        "version: 1\nworking_set: ['src/*.py', 'missing.py']\n",
        encoding="utf-8",
    )
    candidates = ["src/a.py", "src/b.py"]
    with pytest.raises(ScopeExpansionConfirmationRequired):
        save_scope_tiers(
            tmp_path,
            {"src/b.py": 4},
            candidates=candidates,
            previous_tiers={path: 4 for path in candidates},
        )

    save_scope_tiers(
        tmp_path,
        {"src/b.py": 4},
        candidates=candidates,
        previous_tiers={path: 4 for path in candidates},
        confirm_wildcard_expansion=True,
    )
    saved = yaml.safe_load((tmp_path / ".consurg.yaml").read_text(encoding="utf-8"))
    assert saved["working_set"] == ["missing.py", "src/b.py"]


def test_picker_api_rejects_missing_and_invalid_tokens(tmp_path):
    (tmp_path / "safe.py").write_text("safe", encoding="utf-8")
    config = load_file_context_ui_config(tmp_path)
    handler = _make_request_handler(
        tmp_path, config, ["safe.py"], {"safe.py": 1}, "scope", access_token="valid"
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        for token in (None, "invalid"):
            connection = HTTPConnection("127.0.0.1", port, timeout=5)
            headers = {} if token is None else {"X-Consurg-Token": token}
            connection.request("GET", "/api/files", headers=headers)
            response = connection.getresponse()
            response.read()
            connection.close()
            assert response.status == 403

        connection = HTTPConnection("127.0.0.1", port, timeout=5)
        connection.request(
            "POST",
            "/api/compose",
            body="{}",
            headers={"Content-Type": "application/json", "X-Consurg-Token": "invalid"},
        )
        response = connection.getresponse()
        response.read()
        connection.close()
        assert response.status == 403
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_picker_api_requires_wildcard_expansion_confirmation(tmp_path):
    (tmp_path / "src").mkdir()
    for name in ("a.py", "b.py"):
        (tmp_path / "src" / name).write_text(name, encoding="utf-8")
    (tmp_path / ".consurg.yaml").write_text(
        "version: 1\nworking_set: ['src/*.py']\n", encoding="utf-8"
    )
    config = load_file_context_ui_config(tmp_path)
    handler = _make_request_handler(
        tmp_path,
        config,
        ["src/a.py", "src/b.py"],
        {"src/a.py": 4, "src/b.py": 4},
        "scope",
        access_token="valid",
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
        connection.request(
            "POST",
            "/api/save-scope",
            body=json.dumps({"tiers": {"src/b.py": 4}}),
            headers={"Content-Type": "application/json", "X-Consurg-Token": "valid"},
        )
        response = connection.getresponse()
        body = json.loads(response.read())
        connection.close()
        assert response.status == 409
        assert body["requires_wildcard_confirmation"] is True
        assert "src/*.py" in (tmp_path / ".consurg.yaml").read_text(encoding="utf-8")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_save_is_serialized_with_folder_switch(tmp_path, monkeypatch):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "alpha.py").write_text("alpha", encoding="utf-8")
    (second / "beta.py").write_text("beta", encoding="utf-8")
    config = load_file_context_ui_config(first)
    handler = _make_request_handler(
        first, config, ["alpha.py"], {"alpha.py": 1}, "scope", access_token="valid"
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    save_started = threading.Event()
    release_save = threading.Event()
    original_save = file_context_ui.save_scope_tiers

    def delayed_save(*args, **kwargs):
        save_started.set()
        assert release_save.wait(timeout=5)
        return original_save(*args, **kwargs)

    monkeypatch.setattr("consurg.file_context_ui.save_scope_tiers", delayed_save)
    monkeypatch.setattr("consurg.file_context_ui._choose_local_folder", lambda cwd: second)
    port = server.server_address[1]
    headers = {"Content-Type": "application/json", "X-Consurg-Token": "valid"}
    results = {}

    def post(name, path, payload):
        connection = HTTPConnection("127.0.0.1", port, timeout=5)
        connection.request("POST", path, body=json.dumps(payload), headers=headers)
        response = connection.getresponse()
        results[name] = response.status, response.read()
        connection.close()

    try:
        save_thread = threading.Thread(
            target=post, args=("save", "/api/save-scope", {"tiers": {"alpha.py": 4}})
        )
        save_thread.start()
        assert save_started.wait(timeout=5)
        folder_thread = threading.Thread(
            target=post, args=("folder", "/api/open-folder", {})
        )
        folder_thread.start()
        assert folder_thread.is_alive()
        release_save.set()
        save_thread.join(timeout=5)
        folder_thread.join(timeout=5)
        assert results["save"][0] == 200
        assert results["folder"][0] == 200

        connection = HTTPConnection("127.0.0.1", port, timeout=5)
        connection.request("GET", "/api/files", headers={"X-Consurg-Token": "valid"})
        response = connection.getresponse()
        payload = json.loads(response.read())
        connection.close()
        assert response.status == 200
        assert payload["root_name"] == "second"
        assert [item["path"] for item in payload["files"]] == ["beta.py"]
    finally:
        release_save.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_picker_html_exposes_folder_tree_and_chatgpt_actions():
    html = _build_html()

    assert '<html lang="en">' in html
    assert 'class="tree-list"' in html
    assert 'role="tree"' not in html
    assert "checkbox.type = 'checkbox'" in html
    assert 'id="chooseFolder"' in html
    assert "/api/open-folder" in html
    assert "Copy + open ChatGPT" in html


def test_picker_api_switches_folder_and_rejects_forged_denied_paths(
    tmp_path, monkeypatch
):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "alpha.py").write_text("ALPHA_CONTENT", encoding="utf-8")
    (second / "beta.py").write_text("BETA_CONTENT", encoding="utf-8")
    (second / "secret.env").write_text("TOP_SECRET", encoding="utf-8")
    (second / ".consurg.yaml").write_text(
        "file_context_ui:\n  never_include: ['*.env']\n", encoding="utf-8"
    )

    config = load_file_context_ui_config(first)
    handler = _make_request_handler(
        first,
        config,
        ["alpha.py"],
        {"alpha.py": 1},
        "first-scope",
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    origin = f"http://127.0.0.1:{port}"
    token = handler.access_token
    monkeypatch.setattr(
        "consurg.file_context_ui._choose_local_folder", lambda cwd: second
    )

    def request(path, payload, request_origin=origin):
        connection = HTTPConnection("127.0.0.1", port, timeout=5)
        connection.request(
            "POST",
            path,
            body=json.dumps(payload),
            headers={
                "Content-Type": "application/json",
                "Origin": request_origin,
                "X-Consurg-Token": token,
            },
        )
        response = connection.getresponse()
        body = response.read()
        connection.close()
        return response.status, json.loads(body) if response.status < 400 else body

    try:
        status, opened = request("/api/open-folder", {})
        assert status == 200
        assert opened["root_name"] == "second"
        assert any(file["path"] == "beta.py" for file in opened["files"])
        assert next(file for file in opened["files"] if file["path"] == "secret.env")[
            "denied"
        ]
        assert next(file for file in opened["files"] if file["path"] == "secret.env")[
            "tier"
        ] == 0

        status, composed = request(
            "/api/compose",
            {"tiers": {"beta.py": 3, "secret.env": 4}, "format": "markdown"},
        )
        assert status == 200
        assert "BETA_CONTENT" in composed["prompt"]
        assert "TOP_SECRET" not in composed["prompt"]

        status, _ = request(
            "/api/save-scope",
            {"tiers": {"beta.py": 1, "secret.env": 4}, "scope_name": "safe"},
        )
        assert status == 200
        saved = yaml.safe_load((second / ".consurg.yaml").read_text(encoding="utf-8"))
        assert saved["visible"] == ["beta.py"]
        assert saved["working_set"] == []
        assert saved["reference"] == []
        assert saved["signatures"] == []
        assert "secret.env" not in json.dumps(saved)

        status, _ = request("/api/compose", {"tiers": {}}, "http://evil.example")
        assert status == 403
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


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
