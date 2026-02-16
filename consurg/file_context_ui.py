from __future__ import annotations

import json
import socket
import subprocess
import threading
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse
import yaml

from consurg.scope import pattern_matches


TRUNCATION_MARKER = "\n\n[TRUNCATED: total size limit reached]\n"
MISSING_FILE_PLACEHOLDER = "[file not found]"
BINARY_FILE_PLACEHOLDER = "[binary file omitted]"
LARGE_FILE_PLACEHOLDER = "[file exceeds max_file_bytes]"


@dataclass(frozen=True)
class FileContextUIConfig:
    never_include: list[str]
    max_file_bytes: int
    max_total_bytes: int
    hide_excluded: bool


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

    cfg_path = cwd / ".consurg.yaml"
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
        if any(part in ("__pycache__", ".git", ".pytest_cache", "node_modules", ".next", "dist", "venv", ".venv") for part in path.parts):
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


def compose_prompt(paths: list[str], cwd: Path, config: FileContextUIConfig, format: str = "markdown") -> str:
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
    selected = set(_normalize_preselected(preselected or [], cwd))

    handler = _make_request_handler(cwd, config, candidates, selected)

    server = HTTPServer(("127.0.0.1", 0), handler)
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
    preselected: set[Path],
):
    preselected_normalized = {p.as_posix() for p in preselected if p is not None}

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
            if parsed.path != "/api/compose":
                self.send_error(404, "Not found")
                return

            length = int(self.headers.get("Content-Length", "0") or "0")
            body = self.rfile.read(length).decode("utf-8")
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                self.send_error(400, "Invalid JSON")
                return

            selected = payload.get("selected", [])
            fmt = payload.get("format", "markdown")
            if not isinstance(selected, list):
                selected = []
            if fmt not in {"markdown", "plain"}:
                fmt = "markdown"

            prompt = compose_prompt(selected, cwd, config, fmt)
            self._send_json({"prompt": prompt})

        def _files_payload(self):
            result = []
            for path in candidates:
                if is_denied(path, config.never_include) and config.hide_excluded:
                    if path not in preselected_normalized:
                        continue
                result.append(
                    {
                        "path": path,
                        "denied": bool(is_denied(path, config.never_include)),
                        "selected": path in preselected_normalized,
                    }
                )
            return {"files": result}

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
        normalized.relative_to(cwd.resolve())
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
    <title>Consurg File Context</title>
    <style>
      :root {
        --bg: linear-gradient(120deg, #f5f7ff, #eef7ff);
        --card: #ffffffdd;
        --text: #0d1520;
        --muted: #516173;
        --accent: #2d6cdf;
      }
      body {
        margin: 0;
        font-family: ui-sans-serif, "Trebuchet MS", "Segoe UI", sans-serif;
        color: var(--text);
        background: var(--bg);
      }
      .wrap {
        max-width: 1000px;
        margin: 28px auto;
        padding: 20px;
      }
      .panel {
        background: var(--card);
        border: 1px solid #cfd8ea;
        border-radius: 14px;
        box-shadow: 0 16px 40px #0f172a22;
      }
      .header {
        padding: 18px 20px;
        border-bottom: 1px solid #dce3f1;
        font-weight: 700;
        font-size: 1.1rem;
      }
      .row {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 16px;
        padding: 16px;
      }
      .files, .prompt {
        border: 1px solid #dce3f1;
        border-radius: 12px;
        padding: 12px;
      }
      .files-list {
        max-height: 360px;
        overflow: auto;
        margin-top: 10px;
        padding: 4px;
      }
      .file-row {
        display: flex;
        gap: 8px;
        align-items: center;
        padding: 6px 2px;
        border-bottom: 1px dashed #e8edf7;
      }
      .blocked {
        color: #b02c3e;
        font-size: 0.88rem;
      }
      input[type='text'], select, textarea, button {
        border: 1px solid #c7d2e4;
        border-radius: 8px;
        padding: 8px;
      }
      button {
        background: var(--accent);
        border-color: transparent;
        color: white;
        cursor: pointer;
      }
      textarea {
        width: 100%;
        height: 360px;
        box-sizing: border-box;
        resize: vertical;
        font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
      }
      .actions {
        margin-top: 12px;
        display: flex;
        gap: 10px;
      }
      .muted {
        color: var(--muted);
        font-size: 0.95rem;
      }
      .small {
        font-size: 0.88rem;
      }
    </style>
  </head>
  <body>
    <div class="wrap">
      <div class="panel">
        <div class="header">Consurg File Context</div>
        <div class="row">
          <div class="files">
            <div class="small muted">Search and select files to include</div>
            <input type="text" id="search" placeholder="Filter files..." />
            <div id="list" class="files-list"></div>
          </div>
          <div class="prompt">
            <div class="small muted">
              Format:
              <select id="format">
                <option value="markdown">markdown</option>
                <option value="plain">plain</option>
              </select>
            </div>
            <textarea id="prompt" readonly></textarea>
            <div class="actions">
              <button id="copy">Copy</button>
              <button id="download">Download .txt</button>
            </div>
            <div id="status" class="small muted"></div>
          </div>
        </div>
      </div>
    </div>
    <script>
      let files = [];
      let selection = new Set();

      async function loadFiles() {
        const response = await fetch('/api/files');
        const payload = await response.json();
        files = payload.files || [];
        files.forEach((item) => {
          if (item.selected) {
            selection.add(item.path);
          }
        });
        render();
        await refreshPrompt();
      }

      function render() {
        const q = document.getElementById('search').value.toLowerCase();
        const list = document.getElementById('list');
        list.innerHTML = '';
        files
          .filter((f) => f.path.toLowerCase().includes(q))
          .forEach((file) => {
            const row = document.createElement('div');
            row.className = 'file-row';

            const cb = document.createElement('input');
            cb.type = 'checkbox';
            cb.checked = selection.has(file.path);
            cb.disabled = file.denied;
            cb.addEventListener('change', () => {
              if (cb.checked) {
                selection.add(file.path);
              } else {
                selection.delete(file.path);
              }
              refreshPrompt();
            });

            const label = document.createElement('span');
            label.textContent = file.path;

            row.appendChild(cb);
            row.appendChild(label);

            if (file.denied) {
              const blocked = document.createElement('span');
              blocked.className = 'blocked';
              blocked.textContent = ' blocked by policy';
              row.appendChild(blocked);
            }

            list.appendChild(row);
          });
      }

      async function refreshPrompt() {
        const fmt = document.getElementById('format').value;
        const selected = Array.from(selection);
        const response = await fetch('/api/compose', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ selected, format: fmt })
        });
        const payload = await response.json();
        const area = document.getElementById('prompt');
        area.value = payload.prompt || '';
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
        a.download = 'consurg-file-context.txt';
        a.click();
        URL.revokeObjectURL(url);
        setStatus('Downloaded');
      }

      function setStatus(message) {
        document.getElementById('status').textContent = message;
      }

      document.getElementById('search').addEventListener('input', render);
      document.getElementById('format').addEventListener('change', refreshPrompt);
      document.getElementById('copy').addEventListener('click', copyPrompt);
      document.getElementById('download').addEventListener('click', downloadPrompt);

      loadFiles();
    </script>
  </body>
</html>
"""
