from __future__ import annotations

import json
import subprocess
import threading
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from consurg.enforce import resolve_tier
from consurg.render import compose_from_tiers, estimate_file_tokens
from consurg.scope import load_scope, pattern_matches


TRUNCATION_MARKER = "\n\n[TRUNCATED: total size limit reached]\n"
MISSING_FILE_PLACEHOLDER = "[file not found]"
BINARY_FILE_PLACEHOLDER = "[binary file omitted]"
LARGE_FILE_PLACEHOLDER = "[file exceeds max_file_bytes]"

SCOPE_FILE = ".consurg.yaml"


@dataclass(frozen=True)
class FileContextUIConfig:
    never_include: list[str]
    max_file_bytes: int
    max_total_bytes: int
    hide_excluded: bool


IGNORED_DIR_NAMES = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    "node_modules",
    ".next",
    "dist",
    "venv",
    ".venv",
}


_DEFAULT_DENY_PATTERNS = [
    ".git",
    "__pycache__",
    "node_modules",
    "venv",
    ".venv",
    "dist",
    ".pytest_cache",
    ".next",
    "*.pyc",
]


def load_file_context_ui_config(cwd: Path) -> FileContextUIConfig:
    config = _DEFAULT_DENY_PATTERNS.copy()
    max_file_bytes = 20000
    max_total_bytes = 200000
    hide_excluded = False

    cfg_path = cwd / SCOPE_FILE
    if cfg_path.exists():
        with cfg_path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        ui_cfg = data.get("file_context_ui", {})
        if isinstance(ui_cfg, dict):
            cfg_never_include = ui_cfg.get("never_include")
            if isinstance(cfg_never_include, list):
                normalized = [_coerce_pattern(v) for v in cfg_never_include]
                if normalized:
                    config = normalized

            cfg_max_file_bytes = ui_cfg.get("max_file_bytes")
            if isinstance(cfg_max_file_bytes, int) and cfg_max_file_bytes > 0:
                max_file_bytes = cfg_max_file_bytes

            cfg_max_total_bytes = ui_cfg.get("max_total_bytes")
            if isinstance(cfg_max_total_bytes, int) and cfg_max_total_bytes > 0:
                max_total_bytes = cfg_max_total_bytes

            if isinstance(ui_cfg.get("hide_excluded"), bool):
                hide_excluded = ui_cfg.get("hide_excluded")

    return FileContextUIConfig(
        never_include=config,
        max_file_bytes=max_file_bytes,
        max_total_bytes=max_total_bytes,
        hide_excluded=hide_excluded,
    )


def list_candidate_files(cwd: Path, config: FileContextUIConfig | None = None) -> list[str]:
    repo_files: list[str] = []
    try:
        result = subprocess.run(
            ["git", "ls-files"],
            capture_output=True,
            text=True,
            cwd=str(cwd),
        )
        if result.returncode == 0:
            repo_files = [
                str(Path(line.strip()).as_posix())
                for line in result.stdout.strip().splitlines()
                if line.strip()
            ]
    except FileNotFoundError:
        repo_files = []

    if repo_files:
        return sorted(set(repo_files))

    # Fallback to filesystem walk when git is unavailable.
    repo_files = []
    for path in cwd.rglob("*"):
        if not path.is_file():
            continue
        if any(part in IGNORED_DIR_NAMES for part in path.parts):
            continue
        relative = path.relative_to(cwd).as_posix()
        repo_files.append(relative)

    return sorted(set(repo_files))


def is_denied(path: str, deny_patterns: list[str]) -> bool:
    for pattern in deny_patterns:
        normalized_pattern = _coerce_pattern(pattern)
        if not normalized_pattern:
            continue
        normalized_path = _normalize_rel_path(path)
        if pattern_matches(normalized_path, normalized_pattern):
            return True
    return False


def initial_tiers(cwd: Path, candidates: list[str]) -> tuple[dict[str, int], str]:
    """Resolve the starting tier for each candidate from .consurg.yaml.

    Returns ({path: tier}, scope_name). Files without a scope match get tier 0.
    """
    scope = None
    try:
        scope = load_scope(cwd / SCOPE_FILE)
    except Exception:
        scope = None

    if scope is None:
        return ({p: 0 for p in candidates}, "")

    tiers = {}
    for rel in candidates:
        tier, _ = resolve_tier(rel, scope)
        tiers[rel] = tier
    return (tiers, scope.scope_name)


def save_scope_tiers(cwd: Path, tiers: dict[str, int], scope_name: str = "") -> Path:
    """Write explicit per-file tier lists into .consurg.yaml, preserving other keys."""
    scope_path = cwd / SCOPE_FILE
    data: dict = {}
    if scope_path.exists():
        with scope_path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

    data.setdefault("version", 1)
    data["scope"] = scope_name or data.get("scope") or cwd.name
    data.setdefault("active", True)
    data.setdefault("reason", "")

    data["working_set"] = sorted(p for p, t in tiers.items() if t == 4)
    data["reference"] = sorted(p for p, t in tiers.items() if t == 3)
    data["signatures"] = sorted(p for p, t in tiers.items() if t == 2)
    # Tier 1 (existence) is not managed by the picker; preserve what's there.
    data.setdefault("visible", [])
    data.setdefault("dynamic_deps", [])

    with scope_path.open("w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)
    return scope_path


def compose_prompt(paths: list[str], cwd: Path, config: FileContextUIConfig, format: str = "markdown") -> str:
    """Legacy flat-list compose: every path is rendered as full content."""
    safe_paths = []
    for path in paths:
        safe = _safe_relative_path(path, cwd)
        if safe is None:
            continue
        safe_paths.append(safe)

    blocks: list[str] = []
    seen: set[str] = set()
    total_bytes = 0
    truncated = False
    used_marker = False

    for rel_path in safe_paths:
        normalized = rel_path.as_posix()
        if normalized in seen:
            continue
        seen.add(normalized)

        if is_denied(normalized, config.never_include):
            continue

        body, size = _render_file_block(rel_path, cwd, format, config)
        if total_bytes + size > config.max_total_bytes:
            if not used_marker:
                blocks.append(TRUNCATION_MARKER)
                used_marker = True
            truncated = True
            break
        blocks.append(body)
        total_bytes += size

    if truncated:
        return "".join(blocks)

    return "".join(blocks).rstrip()


def start_ui_server(
    cwd: Path,
    config: FileContextUIConfig,
    preselected: list[str] | None = None,
):
    candidates = list_candidate_files(cwd, config)
    tiers, scope_name = initial_tiers(cwd, candidates)

    # Preselected files (CLI args) default to read-write if not already scoped.
    for raw in _normalize_preselected(preselected or [], cwd):
        rel = raw.as_posix()
        if rel in tiers and tiers[rel] == 0:
            tiers[rel] = 4

    handler = _make_request_handler(cwd, config, candidates, tiers, scope_name)

    # Threading matters: browsers hold open preconnect sockets that would
    # deadlock a single-threaded server's accept loop.
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    server_url = f"http://127.0.0.1:{port}/"

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        webbrowser.open(server_url, new=1, autoraise=True)
        print(f"File context UI: {server_url}")
        while True:
            thread.join(1)
            if not thread.is_alive():
                break
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()


def _make_request_handler(
    cwd: Path,
    config: FileContextUIConfig,
    candidates: list[str],
    tiers: dict[str, int],
    scope_name: str,
):
    class FileContextHandler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self._send_html()
            elif parsed.path == "/api/files":
                self._send_json(self._files_payload())
            else:
                self.send_error(404, "Not found")

        def do_POST(self):  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/api/compose":
                self._handle_compose()
            elif parsed.path == "/api/save-scope":
                self._handle_save_scope()
            else:
                self.send_error(404, "Not found")

        def _read_body(self) -> dict | None:
            length = int(self.headers.get("Content-Length", "0") or "0")
            body = self.rfile.read(length).decode("utf-8")
            try:
                return json.loads(body)
            except json.JSONDecodeError:
                self.send_error(400, "Invalid JSON")
                return None

        def _handle_compose(self):
            payload = self._read_body()
            if payload is None:
                return

            requested = _sanitize_tiers(payload.get("tiers"), cwd)
            fmt = payload.get("format", "markdown")
            if fmt not in {"markdown", "plain", "xml"}:
                fmt = "markdown"
            task = payload.get("task", "")
            if not isinstance(task, str):
                task = ""

            result = compose_from_tiers(
                requested,
                cwd,
                limits=config,
                fmt=fmt,
                task=task,
                scope_name=payload.get("scope_name") or scope_name,
            )
            self._send_json(
                {
                    "prompt": result.text,
                    "tokens": result.token_estimate,
                    "included": len(result.included),
                    "skipped": [
                        {"path": p, "reason": why} for p, why in result.skipped
                    ],
                }
            )

        def _handle_save_scope(self):
            payload = self._read_body()
            if payload is None:
                return
            requested = _sanitize_tiers(payload.get("tiers"), cwd)
            name = payload.get("scope_name", "")
            if not isinstance(name, str):
                name = ""
            path = save_scope_tiers(cwd, requested, scope_name=name.strip())
            self._send_json({"saved": str(path)})

        def _files_payload(self):
            result = []
            for path in candidates:
                denied = is_denied(path, config.never_include)
                if denied and config.hide_excluded and tiers.get(path, 0) == 0:
                    continue
                result.append(
                    {
                        "path": path,
                        "tier": tiers.get(path, 0),
                        "denied": denied,
                        "tokens": estimate_file_tokens(cwd / path),
                    }
                )
            return {"files": result, "scope_name": scope_name}

        def _send_json(self, payload: dict):
            payload_text = json.dumps(payload)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload_text.encode("utf-8"))))
            self.end_headers()
            self.wfile.write(payload_text.encode("utf-8"))

        def _send_html(self):
            page = _build_html()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page.encode("utf-8"))))
            self.end_headers()
            self.wfile.write(page.encode("utf-8"))

        def log_message(self, format, *args):  # noqa: A003
            return

    return FileContextHandler


def _sanitize_tiers(raw: Any, cwd: Path) -> dict[str, int]:
    """Validate a client-supplied {path: tier} map: safe paths, tiers 0-4."""
    tiers: dict[str, int] = {}
    if not isinstance(raw, dict):
        return tiers
    for path, tier in raw.items():
        if not isinstance(path, str):
            continue
        try:
            tier_int = int(tier)
        except (TypeError, ValueError):
            continue
        if tier_int < 1 or tier_int > 4:
            continue
        safe = _safe_relative_path(path, cwd)
        if safe is None:
            continue
        tiers[safe.as_posix()] = tier_int
    return tiers


def _render_file_block(
    rel_path: Path,
    cwd: Path,
    fmt: str,
    config: FileContextUIConfig,
) -> tuple[str, int]:
    full_path = cwd / rel_path
    if not full_path.exists():
        content = _file_prompt_block(rel_path.as_posix(), MISSING_FILE_PLACEHOLDER, fmt)
        return content, len(content.encode("utf-8"))

    try:
        size = full_path.stat().st_size
    except OSError:
        size = 0

    if size > config.max_file_bytes:
        content = _file_prompt_block(rel_path.as_posix(), LARGE_FILE_PLACEHOLDER, fmt)
        return content, len(content.encode("utf-8"))

    try:
        with full_path.open("rb") as f:
            chunk = f.read(8192)
    except OSError:
        content = _file_prompt_block(rel_path.as_posix(), MISSING_FILE_PLACEHOLDER, fmt)
        return content, len(content.encode("utf-8"))

    if b"\x00" in chunk:
        content = _file_prompt_block(rel_path.as_posix(), BINARY_FILE_PLACEHOLDER, fmt)
        return content, len(content.encode("utf-8"))

    try:
        body = full_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        body = full_path.read_bytes().decode("utf-8", errors="replace")

    full_content = _file_prompt_block(rel_path.as_posix(), body, fmt)
    return full_content, len(full_content.encode("utf-8"))


def _file_prompt_block(path: str, body: str, fmt: str) -> str:
    if fmt == "plain":
        return f"{path}\n{'-' * max(3, len(path))}\n{body}\n\n"

    language = _infer_language(path)
    return f"## FILE: {path}\n```{language}\n{body}\n```\n\n"


def _infer_language(path: str) -> str:
    suffix = Path(path).suffix.lower().lstrip(".")
    if not suffix:
        return ""
    return suffix


def _safe_relative_path(path: str, cwd: Path) -> Path | None:
    p = Path(path)
    if not p.is_absolute():
        p = cwd / p
    try:
        normalized = p.resolve()
    except OSError:
        normalized = p.resolve(strict=False)

    try:
        return normalized.relative_to(cwd.resolve())
    except ValueError:
        return None


def _normalize_preselected(raw_files: list[str], cwd: Path) -> set[Path]:
    result: set[Path] = set()
    for raw in raw_files:
        path = _safe_relative_path(raw, cwd)
        if path is not None:
            result.add(path)
    return result


def _coerce_pattern(pattern: Any) -> str:
    if pattern is None:
        return ""
    return str(pattern).replace("\\", "/").strip()


def _normalize_rel_path(path: str) -> str:
    normalized = _coerce_pattern(path)
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _build_html() -> str:
    return """<!doctype html>
<html>
  <head>
    <meta charset=\"utf-8\" />
    <title>Consurg Scope Picker</title>
    <style>
      :root {
        --bg: linear-gradient(120deg, #f5f7ff, #eef7ff);
        --card: #ffffffdd;
        --text: #0d1520;
        --muted: #516173;
        --accent: #2d6cdf;
        --rw: #1d7a3d;
        --ro: #2d6cdf;
        --sig: #9a6b00;
      }
      body {
        margin: 0;
        font-family: ui-sans-serif, "Trebuchet MS", "Segoe UI", sans-serif;
        color: var(--text);
        background: var(--bg);
      }
      .wrap { max-width: 1200px; margin: 24px auto; padding: 16px; }
      .panel {
        background: var(--card);
        border: 1px solid #cfd8ea;
        border-radius: 14px;
        box-shadow: 0 16px 40px #0f172a22;
      }
      .header {
        padding: 14px 20px;
        border-bottom: 1px solid #dce3f1;
        display: flex;
        align-items: baseline;
        gap: 14px;
      }
      .header .title { font-weight: 700; font-size: 1.1rem; }
      .header input { width: 200px; }
      .row {
        display: grid;
        grid-template-columns: 1.2fr 1fr;
        gap: 16px;
        padding: 16px;
      }
      .files, .prompt {
        border: 1px solid #dce3f1;
        border-radius: 12px;
        padding: 12px;
      }
      .files-list { max-height: 480px; overflow: auto; margin-top: 10px; }
      .file-row {
        display: flex;
        gap: 8px;
        align-items: center;
        padding: 4px 2px;
        border-bottom: 1px dashed #e8edf7;
        font-size: 0.92rem;
      }
      .file-row .path { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-family: ui-monospace, Consolas, monospace; }
      .file-row .tokens { color: var(--muted); font-size: 0.8rem; min-width: 60px; text-align: right; }
      .tier-btns { display: flex; gap: 2px; }
      .tier-btns button {
        border: 1px solid #c7d2e4;
        background: #f6f8fc;
        color: var(--muted);
        border-radius: 6px;
        padding: 2px 7px;
        font-size: 0.78rem;
        cursor: pointer;
      }
      .tier-btns button.on-4 { background: var(--rw); color: white; border-color: transparent; }
      .tier-btns button.on-3 { background: var(--ro); color: white; border-color: transparent; }
      .tier-btns button.on-2 { background: var(--sig); color: white; border-color: transparent; }
      .tier-btns button.on-0 { background: #64748b; color: white; border-color: transparent; }
      .blocked { color: #b02c3e; font-size: 0.8rem; }
      input[type='text'], select, textarea, button.action {
        border: 1px solid #c7d2e4;
        border-radius: 8px;
        padding: 8px;
      }
      button.action {
        background: var(--accent);
        border-color: transparent;
        color: white;
        cursor: pointer;
      }
      button.action.secondary { background: #475569; }
      textarea#prompt {
        width: 100%;
        height: 340px;
        box-sizing: border-box;
        resize: vertical;
        font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
        font-size: 0.85rem;
      }
      textarea#task {
        width: 100%;
        height: 54px;
        box-sizing: border-box;
        resize: vertical;
        margin-top: 6px;
      }
      .actions { margin-top: 12px; display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
      .muted { color: var(--muted); font-size: 0.92rem; }
      .small { font-size: 0.85rem; }
      .totals { font-weight: 700; }
      .legend span { margin-right: 10px; }
      .bulk { margin-top: 8px; display: flex; gap: 6px; align-items: center; font-size: 0.85rem; }
    </style>
  </head>
  <body>
    <div class="wrap">
      <div class="panel">
        <div class="header">
          <span class="title">Consurg Scope Picker</span>
          <span class="small muted">Scope name:</span>
          <input type="text" id="scopeName" placeholder="scope name" />
          <span class="small muted legend">
            <span><b style="color:var(--rw)">RW</b> full read-write</span>
            <span><b style="color:var(--ro)">RO</b> read-only</span>
            <span><b style="color:var(--sig)">SIG</b> signatures only</span>
            <span><b>OFF</b> excluded</span>
          </span>
        </div>
        <div class="row">
          <div class="files">
            <div class="small muted">Pick each file's tier — the same selection drives the agent guard and the copy-paste prompt</div>
            <input type="text" id="search" placeholder="Filter files..." style="width:100%; box-sizing:border-box; margin-top:6px;" />
            <div class="bulk">
              <span class="muted">Set all filtered:</span>
              <button data-bulk="4">RW</button>
              <button data-bulk="3">RO</button>
              <button data-bulk="2">SIG</button>
              <button data-bulk="0">OFF</button>
            </div>
            <div id="list" class="files-list"></div>
          </div>
          <div class="prompt">
            <div class="small muted">
              Format:
              <select id="format">
                <option value="markdown">markdown</option>
                <option value="xml">xml</option>
                <option value="plain">plain</option>
              </select>
              &nbsp; <span class="totals" id="totals"></span>
            </div>
            <textarea id="task" placeholder="Optional task / instructions to prepend..."></textarea>
            <textarea id="prompt" readonly></textarea>
            <div class="actions">
              <button class="action" id="copy">Copy prompt</button>
              <button class="action" id="download">Download .txt</button>
              <button class="action secondary" id="save">Save scope (.consurg.yaml)</button>
            </div>
            <div id="status" class="small muted"></div>
          </div>
        </div>
      </div>
    </div>
    <script>
      let files = [];
      let tiers = {};
      let composeTimer = null;

      const TIER_LABELS = { 4: 'RW', 3: 'RO', 2: 'SIG', 0: 'OFF' };

      async function loadFiles() {
        const response = await fetch('/api/files');
        const payload = await response.json();
        files = payload.files || [];
        document.getElementById('scopeName').value = payload.scope_name || '';
        files.forEach((item) => {
          tiers[item.path] = item.tier === 1 ? 0 : item.tier;
        });
        render();
        scheduleCompose();
      }

      function filteredFiles() {
        const q = document.getElementById('search').value.toLowerCase();
        return files.filter((f) => f.path.toLowerCase().includes(q));
      }

      function render() {
        const list = document.getElementById('list');
        list.innerHTML = '';
        filteredFiles().forEach((file) => {
          const row = document.createElement('div');
          row.className = 'file-row';

          const btns = document.createElement('div');
          btns.className = 'tier-btns';
          [4, 3, 2, 0].forEach((tier) => {
            const b = document.createElement('button');
            b.textContent = TIER_LABELS[tier];
            if (tiers[file.path] === tier) {
              b.className = 'on-' + tier;
            }
            b.disabled = file.denied && tier !== 0;
            b.addEventListener('click', () => {
              tiers[file.path] = tier;
              render();
              scheduleCompose();
            });
            btns.appendChild(b);
          });

          const label = document.createElement('span');
          label.className = 'path';
          label.textContent = file.path;
          label.title = file.path;

          const tokens = document.createElement('span');
          tokens.className = 'tokens';
          tokens.textContent = '~' + file.tokens + ' tok';

          row.appendChild(btns);
          row.appendChild(label);
          if (file.denied) {
            const blocked = document.createElement('span');
            blocked.className = 'blocked';
            blocked.textContent = 'policy';
            row.appendChild(blocked);
          }
          row.appendChild(tokens);
          list.appendChild(row);
        });
        updateTotals();
      }

      function selectedTiers() {
        const out = {};
        Object.entries(tiers).forEach(([path, tier]) => {
          if (tier >= 2) { out[path] = tier; }
        });
        return out;
      }

      function updateTotals(serverTokens) {
        const sel = selectedTiers();
        const count = Object.keys(sel).length;
        let est = 0;
        files.forEach((f) => {
          const t = sel[f.path];
          if (t === 4 || t === 3) { est += f.tokens; }
          else if (t === 2) { est += Math.min(f.tokens, 150); }
        });
        const shown = serverTokens != null ? serverTokens : est;
        document.getElementById('totals').textContent =
          count + ' files, ~' + shown.toLocaleString() + ' tokens';
      }

      function scheduleCompose() {
        clearTimeout(composeTimer);
        composeTimer = setTimeout(refreshPrompt, 250);
      }

      async function refreshPrompt() {
        const fmt = document.getElementById('format').value;
        const task = document.getElementById('task').value;
        const response = await fetch('/api/compose', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            tiers: selectedTiers(),
            format: fmt,
            task: task,
            scope_name: document.getElementById('scopeName').value,
          })
        });
        const payload = await response.json();
        document.getElementById('prompt').value = payload.prompt || '';
        updateTotals(payload.tokens);
        if (payload.skipped && payload.skipped.length) {
          setStatus('Omitted: ' + payload.skipped.map((s) => s.path + ' (' + s.reason + ')').join(', '));
        } else {
          setStatus('');
        }
      }

      async function copyPrompt() {
        const text = document.getElementById('prompt').value;
        try {
          await navigator.clipboard.writeText(text);
          setStatus('Copied to clipboard');
        } catch {
          setStatus('Copy failed. Use Ctrl+C to copy manually.');
        }
      }

      function downloadPrompt() {
        const text = document.getElementById('prompt').value;
        const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'consurg-context.txt';
        a.click();
        URL.revokeObjectURL(url);
        setStatus('Downloaded');
      }

      async function saveScope() {
        const response = await fetch('/api/save-scope', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            tiers: selectedTiers(),
            scope_name: document.getElementById('scopeName').value,
          })
        });
        const payload = await response.json();
        setStatus('Scope saved to ' + (payload.saved || '.consurg.yaml') + ' — ready for consurg run');
      }

      function setStatus(message) {
        document.getElementById('status').textContent = message;
      }

      document.getElementById('search').addEventListener('input', render);
      document.getElementById('format').addEventListener('change', scheduleCompose);
      document.getElementById('task').addEventListener('input', scheduleCompose);
      document.getElementById('copy').addEventListener('click', copyPrompt);
      document.getElementById('download').addEventListener('click', downloadPrompt);
      document.getElementById('save').addEventListener('click', saveScope);
      document.querySelectorAll('[data-bulk]').forEach((btn) => {
        btn.addEventListener('click', () => {
          const tier = parseInt(btn.getAttribute('data-bulk'), 10);
          filteredFiles().forEach((f) => {
            if (!f.denied || tier === 0) { tiers[f.path] = tier; }
          });
          render();
          scheduleCompose();
        });
      });

      loadFiles();
    </script>
  </body>
</html>
"""
