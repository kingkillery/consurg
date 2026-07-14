from __future__ import annotations

import json
import os
import secrets
import subprocess
import threading
import tempfile
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import yaml

from consurg.enforce import resolve_tier
from consurg.render import (
    HARD_MAX_FILE_BYTES,
    HARD_MAX_TOTAL_BYTES,
    compose_from_tiers,
    estimate_file_tokens,
    safe_read_context_file,
)
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
    ".llm-router",
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
    ".llm-router",
    ".next",
    "*.pyc",
]


def load_file_context_ui_config(cwd: Path) -> FileContextUIConfig:
    config = _DEFAULT_DENY_PATTERNS.copy()
    max_file_bytes = 20000
    max_total_bytes = 200000
    hide_excluded = False

    cfg_path = cwd / SCOPE_FILE
    data: dict[str, Any] = {}
    if cfg_path.exists():
        try:
            with cfg_path.open(encoding="utf-8") as f:
                loaded = yaml.safe_load(f) or {}
            if isinstance(loaded, dict):
                data = loaded
        except (OSError, yaml.YAMLError):
            data = {}

    ui_cfg = data.get("file_context_ui", {})
    if isinstance(ui_cfg, dict):
        cfg_never_include = ui_cfg.get("never_include")
        if isinstance(cfg_never_include, list):
            normalized = [_coerce_pattern(value) for value in cfg_never_include]
            if normalized:
                config = normalized

        cfg_max_file_bytes = ui_cfg.get("max_file_bytes")
        if (
            isinstance(cfg_max_file_bytes, int)
            and not isinstance(cfg_max_file_bytes, bool)
            and cfg_max_file_bytes > 0
        ):
            max_file_bytes = min(cfg_max_file_bytes, HARD_MAX_FILE_BYTES)

        cfg_max_total_bytes = ui_cfg.get("max_total_bytes")
        if (
            isinstance(cfg_max_total_bytes, int)
            and not isinstance(cfg_max_total_bytes, bool)
            and cfg_max_total_bytes > 0
        ):
            max_total_bytes = min(cfg_max_total_bytes, HARD_MAX_TOTAL_BYTES)

        if isinstance(ui_cfg.get("hide_excluded"), bool):
            hide_excluded = ui_cfg["hide_excluded"]

    return FileContextUIConfig(
        never_include=config,
        max_file_bytes=max_file_bytes,
        max_total_bytes=max_total_bytes,
        hide_excluded=hide_excluded,
    )


def list_candidate_files(
    cwd: Path, config: FileContextUIConfig | None = None
) -> list[str]:
    repo_files: list[str] = []
    try:
        result = subprocess.run(
            [
                "git",
                "-c",
                "core.quotepath=false",
                "ls-files",
                "-z",
                "--cached",
                "--others",
                "--exclude-standard",
            ],
            capture_output=True,
            cwd=str(cwd),
            timeout=10,
            check=False,
        )
        if result.returncode == 0:
            stdout = result.stdout
            entries = (
                stdout.split(b"\0")
                if isinstance(stdout, bytes)
                else stdout.split("\0")
            )
            for entry in entries:
                if isinstance(entry, bytes):
                    line = entry.decode("utf-8", errors="surrogateescape")
                else:
                    line = entry
                if not line:
                    continue
                normalized = Path(line).as_posix()
                if not normalized:
                    continue
                candidate = cwd / normalized
                if candidate.is_file() and not any(
                    part in IGNORED_DIR_NAMES for part in Path(normalized).parts
                ):
                    repo_files.append(normalized)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        repo_files = []

    if repo_files:
        return sorted(set(repo_files))

    # Fallback to a pruned filesystem walk when git is unavailable.
    repo_files = []
    for root, dir_names, file_names in os.walk(cwd, topdown=True, followlinks=False):
        dir_names[:] = sorted(
            name for name in dir_names if name not in IGNORED_DIR_NAMES
        )
        root_path = Path(root)
        for file_name in sorted(file_names):
            path = root_path / file_name
            if path.is_file():
                repo_files.append(path.relative_to(cwd).as_posix())

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


def initial_tiers(
    cwd: Path, candidates: list[str], config: FileContextUIConfig | None = None
) -> tuple[dict[str, int], str]:
    """Resolve the starting tier for each candidate from .consurg.yaml.

    Returns ({path: tier}, scope_name). Files without a scope match get tier 0.
    """
    try:
        scope = load_scope(cwd / SCOPE_FILE)
    except Exception:
        scope = None
    if scope is None:
        return ({p: 0 for p in candidates}, "")

    tiers = {}
    for rel in candidates:
        tier, _ = resolve_tier(rel, scope)
        tiers[rel] = 0 if config and is_denied(rel, config.never_include) else tier
    return (tiers, scope.scope_name)

class ScopeExpansionConfirmationRequired(Exception):
    """Raised before turning selected wildcard matches into explicit paths."""


def save_scope_tiers(
    cwd: Path,
    tiers: dict[str, int],
    scope_name: str = "",
    *,
    manage_visible: bool = False,
    candidates: list[str] | None = None,
    previous_tiers: dict[str, int] | None = None,
    confirm_wildcard_expansion: bool = False,
) -> Path:
    """Write explicit per-file tiers into .consurg.yaml, preserving other keys."""
    scope_path = cwd / SCOPE_FILE
    data: dict[str, Any] = {}
    if scope_path.exists():
        with scope_path.open(encoding="utf-8") as f:
            loaded = yaml.safe_load(f) or {}
        if isinstance(loaded, dict):
            data = loaded

    data.setdefault("version", 1)
    data["scope"] = scope_name or data.get("scope") or cwd.name
    data.setdefault("active", True)
    data.setdefault("reason", "")

    if candidates is None or previous_tiers is None:
        data["working_set"] = sorted(path for path, tier in tiers.items() if tier == 4)
        data["reference"] = sorted(path for path, tier in tiers.items() if tier == 3)
        data["signatures"] = sorted(path for path, tier in tiers.items() if tier == 2)
        if manage_visible:
            data["visible"] = sorted(path for path, tier in tiers.items() if tier == 1)
        else:
            data.setdefault("visible", [])
    else:
        _update_scope_entries(
            data,
            tiers,
            candidates,
            previous_tiers,
            manage_visible=manage_visible,
            confirm_wildcard_expansion=confirm_wildcard_expansion,
        )
    data.setdefault("dynamic_deps", [])

    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=cwd,
            prefix=".consurg-",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            yaml.dump(data, temp_file, default_flow_style=False, sort_keys=False)
            temp_path = Path(temp_file.name)
        os.replace(temp_path, scope_path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()
    return scope_path


def compose_prompt(
    paths: list[str], cwd: Path, config: FileContextUIConfig, format: str = "markdown"
) -> str:
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
        if total_bytes + size > min(config.max_total_bytes, HARD_MAX_TOTAL_BYTES):
            if not used_marker:
                marker = (
                    "<truncated>total size limit reached</truncated>\n"
                    if format == "xml"
                    else TRUNCATION_MARKER
                )
                blocks.append(marker)
            truncated = True
            break
        blocks.append(body)
        total_bytes += size

    rendered = "".join(blocks)
    if format == "xml":
        return f"<context>\n{rendered}</context>"
    if truncated:
        return rendered
    return rendered.rstrip()


def start_ui_server(
    cwd: Path,
    config: FileContextUIConfig,
    preselected: list[str] | None = None,
):
    candidates = list_candidate_files(cwd, config)
    tiers, scope_name = initial_tiers(cwd, candidates, config)

    # Preselected files (CLI args) default to read-write if not already scoped.
    for raw in _normalize_preselected(preselected or [], cwd):
        rel = raw.as_posix()
        if rel in tiers and tiers[rel] == 0:
            tiers[rel] = 4

    access_token = secrets.token_urlsafe(32)
    handler = _make_request_handler(
        cwd,
        config,
        candidates,
        tiers,
        scope_name,
        access_token=access_token,
    )

    # Threading matters: browsers hold open preconnect sockets that would
    # deadlock a single-threaded server's accept loop.
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server.daemon_threads = True
    port = server.server_address[1]
    server_url = f"http://127.0.0.1:{port}/?token={access_token}"

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
    *,
    access_token: str | None = None,
):
    server_token = access_token or secrets.token_urlsafe(32)
    state: dict[str, Any] = {
        "cwd": cwd,
        "config": config,
        "candidates": candidates,
        "tiers": {
            path: 0 if is_denied(path, config.never_include) else tiers.get(path, 0)
            for path in candidates
        },
        "scope_name": scope_name,
    }
    state_lock = threading.RLock()
    folder_picker_lock = threading.Lock()

    class FileContextHandler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/":
                supplied = parse_qs(parsed.query).get("token", [""])[0]
                if not secrets.compare_digest(supplied, server_token):
                    self.send_error(403, "Invalid picker token")
                    return
                self._send_html()
            elif parsed.path == "/api/files":
                if not self._authorized_request():
                    self.send_error(403, "Invalid picker token")
                    return
                self._send_json(self._files_payload())
            else:
                self.send_error(404, "Not found")

        def do_POST(self):  # noqa: N802
            if not self._same_origin_request():
                self._drain_request_body()
                self.send_error(403, "Cross-origin requests are not allowed")
                return
            if not self._authorized_request():
                self._drain_request_body()
                self.send_error(403, "Invalid picker token")
                return
            parsed = urlparse(self.path)
            if parsed.path == "/api/compose":
                self._handle_compose()
            elif parsed.path == "/api/save-scope":
                self._handle_save_scope()
            elif parsed.path == "/api/open-folder":
                self._handle_open_folder()
            else:
                self.send_error(404, "Not found")

        def _authorized_request(self) -> bool:
            supplied = self.headers.get("X-Consurg-Token", "")
            return secrets.compare_digest(supplied, server_token)

        def _drain_request_body(self) -> None:
            """Consume the declared request body before rejecting.

            Responding and closing while the client is still sending can abort
            the connection on Windows (WinError 10053) before the client reads
            the status line. Bounded to avoid slow-upload abuse.
            """
            try:
                length = int(self.headers.get("Content-Length", "0") or "0")
            except ValueError:
                return
            remaining = min(max(length, 0), 1_000_000)
            while remaining > 0:
                chunk = self.rfile.read(min(remaining, 65536))
                if not chunk:
                    break
                remaining -= len(chunk)

        def _same_origin_request(self) -> bool:
            origin = self.headers.get("Origin")
            host = self.headers.get("Host")
            return not origin or (
                host is not None and origin.rstrip("/") == f"http://{host}"
            )

        def _read_body(self) -> dict | None:
            try:
                length = int(self.headers.get("Content-Length", "0") or "0")
            except ValueError:
                self.send_error(400, "Invalid Content-Length")
                return None
            if length < 0 or length > 1_000_000:
                self.send_error(413, "Request body is too large")
                return None
            try:
                body = self.rfile.read(length).decode("utf-8")
                payload = json.loads(body)
            except (UnicodeDecodeError, json.JSONDecodeError):
                self.send_error(400, "Invalid JSON")
                return None
            if not isinstance(payload, dict):
                self.send_error(400, "JSON body must be an object")
                return None
            return payload

        def _state_snapshot(
            self,
        ) -> tuple[Path, FileContextUIConfig, list[str], dict[str, int], str]:
            with state_lock:
                return (
                    state["cwd"],
                    state["config"],
                    list(state["candidates"]),
                    dict(state["tiers"]),
                    state["scope_name"],
                )

        def _handle_compose(self):
            payload = self._read_body()
            if payload is None:
                return
            current_cwd, current_config, current_candidates, _, current_scope = (
                self._state_snapshot()
            )
            requested = _sanitize_tiers(
                payload.get("tiers"),
                current_cwd,
                allowed_paths=set(current_candidates),
                deny_patterns=current_config.never_include,
            )
            fmt = payload.get("format", "markdown")
            if fmt not in {"markdown", "plain", "xml"}:
                fmt = "markdown"
            task = payload.get("task", "")
            if not isinstance(task, str):
                task = ""
            requested_scope = payload.get("scope_name")
            if not isinstance(requested_scope, str):
                requested_scope = ""
            requested_scope = requested_scope.strip()[:120]

            result = compose_from_tiers(
                requested,
                current_cwd,
                limits=current_config,
                fmt=fmt,
                task=task,
                scope_name=requested_scope or current_scope,
            )
            self._send_json(
                {
                    "prompt": result.text,
                    "tokens": result.token_estimate,
                    "included": len(result.included),
                    "skipped": [
                        {"path": path, "reason": reason}
                        for path, reason in result.skipped
                    ],
                }
            )

        def _handle_save_scope(self):
            payload = self._read_body()
            if payload is None:
                return
            name = payload.get("scope_name", "")
            if not isinstance(name, str):
                name = ""
            name = name.strip()[:120]
            confirmed = payload.get("confirm_wildcard_expansion") is True
            with state_lock:
                current_cwd = state["cwd"]
                current_config = state["config"]
                current_candidates = list(state["candidates"])
                previous_tiers = dict(state["tiers"])
                requested = _sanitize_tiers(
                    payload.get("tiers"),
                    current_cwd,
                    allowed_paths=set(current_candidates),
                    deny_patterns=current_config.never_include,
                )
                try:
                    path = save_scope_tiers(
                        current_cwd,
                        requested,
                        scope_name=name,
                        manage_visible=True,
                        candidates=current_candidates,
                        previous_tiers=previous_tiers,
                        confirm_wildcard_expansion=confirmed,
                    )
                except ScopeExpansionConfirmationRequired:
                    self._send_json(
                        {
                            "error": "Saving these edits expands wildcard scope entries",
                            "requires_wildcard_confirmation": True,
                        },
                        status=409,
                    )
                    return
                except (OSError, yaml.YAMLError) as exc:
                    self._send_json(
                        {"error": f"Could not save the scope: {exc}"}, status=500
                    )
                    return
                state["tiers"] = {
                    path: requested.get(path, 0) for path in current_candidates
                }
                state["scope_name"] = name or state["scope_name"]
            self._send_json({"saved": str(path)})

        def _handle_open_folder(self):
            if self._read_body() is None:
                return
            if not folder_picker_lock.acquire(blocking=False):
                self._send_json(
                    {"error": "A folder picker is already open"}, status=409
                )
                return
            try:
                with state_lock:
                    current_cwd = state["cwd"]
                    try:
                        selected = _choose_local_folder(current_cwd)
                    except RuntimeError as exc:
                        self._send_json({"error": str(exc)}, status=501)
                        return
                    if selected is None:
                        self._send_json({"cancelled": True})
                        return

                    new_config = load_file_context_ui_config(selected)
                    new_candidates = list_candidate_files(selected, new_config)
                    new_tiers, new_scope_name = initial_tiers(
                        selected, new_candidates, new_config
                    )
                    state.update(
                        {
                            "cwd": selected,
                            "config": new_config,
                            "candidates": new_candidates,
                            "tiers": new_tiers,
                            "scope_name": new_scope_name,
                        }
                    )
                    response = self._files_payload()
                response["changed"] = True
                self._send_json(response)
            except OSError as exc:
                self._send_json(
                    {"error": f"Could not open the folder: {exc}"}, status=500
                )
            finally:
                folder_picker_lock.release()

        def _files_payload(self):
            (
                current_cwd,
                current_config,
                current_candidates,
                current_tiers,
                current_scope,
            ) = self._state_snapshot()
            result = []
            for path in current_candidates:
                denied = is_denied(path, current_config.never_include)
                if (
                    denied
                    and current_config.hide_excluded
                    and current_tiers.get(path, 0) == 0
                ):
                    continue
                safe = _safe_relative_path(path, current_cwd)
                if safe is None:
                    continue
                result.append(
                    {
                        "path": path,
                        "tier": current_tiers.get(path, 0),
                        "denied": denied,
                        "tokens": estimate_file_tokens(current_cwd / safe),
                    }
                )
            return {
                "files": result,
                "scope_name": current_scope,
                "root_name": current_cwd.name or str(current_cwd),
            }

        def _security_headers(self):
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
                "connect-src 'self'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'",
            )

        def _send_json(self, payload: dict, status: int = 200):
            payload_text = json.dumps(payload)
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload_text.encode("utf-8"))))
            self._security_headers()
            self.end_headers()
            try:
                self.wfile.write(payload_text.encode("utf-8"))
            except (BrokenPipeError, ConnectionResetError):
                pass

        def _send_html(self):
            page = _build_html(server_token)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page.encode("utf-8"))))
            self._security_headers()
            self.end_headers()
            try:
                self.wfile.write(page.encode("utf-8"))
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, format, *args):  # noqa: A003
            return

    FileContextHandler.access_token = server_token
    return FileContextHandler


def _sanitize_tiers(
    raw: Any,
    cwd: Path,
    *,
    allowed_paths: set[str] | None = None,
    deny_patterns: list[str] | None = None,
) -> dict[str, int]:
    """Validate a client-supplied tier map against the current local root."""
    tiers: dict[str, int] = {}
    if not isinstance(raw, dict):
        return tiers
    normalized_allowed = (
        {_normalize_rel_path(path) for path in allowed_paths}
        if allowed_paths is not None
        else None
    )
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
        normalized = safe.as_posix()
        if normalized_allowed is not None and normalized not in normalized_allowed:
            continue
        if deny_patterns and is_denied(normalized, deny_patterns):
            continue
        tiers[normalized] = tier_int
    return tiers


def _render_file_block(
    rel_path: Path,
    cwd: Path,
    fmt: str,
    config: FileContextUIConfig,
) -> tuple[str, int]:
    body, omission_reason = safe_read_context_file(
        cwd / rel_path, cwd, config.max_file_bytes
    )
    placeholders = {
        "file not found": MISSING_FILE_PLACEHOLDER,
        "unreadable": MISSING_FILE_PLACEHOLDER,
        "binary file": BINARY_FILE_PLACEHOLDER,
        "exceeds max_file_bytes": LARGE_FILE_PLACEHOLDER,
    }
    rendered_body = placeholders.get(omission_reason, body or MISSING_FILE_PLACEHOLDER)
    content = _file_prompt_block(rel_path.as_posix(), rendered_body, fmt)
    return content, len(content.encode("utf-8"))


def _has_wildcard(pattern: str) -> bool:
    return any(marker in pattern for marker in ("*", "?", "["))


def _update_scope_entries(
    data: dict[str, Any],
    tiers: dict[str, int],
    candidates: list[str],
    previous_tiers: dict[str, int],
    *,
    manage_visible: bool,
    confirm_wildcard_expansion: bool,
) -> None:
    keys = ((4, "working_set"), (3, "reference"), (2, "signatures"), (1, "visible"))
    changed = {
        path
        for path in candidates
        if tiers.get(path, 0) != previous_tiers.get(path, 0)
    }
    if not changed:
        return

    entries = {
        key: [entry for entry in data.get(key, []) if isinstance(entry, str)]
        for _, key in keys
    }
    relevant = [
        entry
        for values in entries.values()
        for entry in values
        if any(pattern_matches(path, entry) for path in changed)
    ]
    if not confirm_wildcard_expansion and any(_has_wildcard(entry) for entry in relevant):
        raise ScopeExpansionConfirmationRequired

    rewritten = set(changed)
    while True:
        matching_entries = [
            entry
            for values in entries.values()
            for entry in values
            if any(pattern_matches(path, entry) for path in rewritten)
        ]
        expanded = rewritten | {
            path
            for path in candidates
            if any(pattern_matches(path, entry) for entry in matching_entries)
        }
        if expanded == rewritten:
            break
        rewritten = expanded

    for tier, key in keys:
        if tier == 1 and not manage_visible:
            data.setdefault(key, [])
            continue
        retained = [
            entry
            for entry in entries[key]
            if not any(pattern_matches(path, entry) for path in rewritten)
        ]
        retained.extend(
            path for path in rewritten if tiers.get(path, 0) == tier
        )
        data[key] = sorted(set(retained))


def _file_prompt_block(path: str, body: str, fmt: str) -> str:
    if fmt == "xml":
        return f'<file path="{_xml_escape(path)}">{_xml_escape(body)}</file>\n'
    if fmt == "plain":
        return f"{path}\n{'-' * max(3, len(path))}\n{body}\n\n"

    language = _infer_language(path)
    return f"## FILE: {path}\n```{language}\n{body}\n```\n\n"


def _xml_escape(text: str) -> str:
    valid = "".join(
        char
        for char in text
        if ord(char) in (0x9, 0xA, 0xD)
        or 0x20 <= ord(char) <= 0xD7FF
        or 0xE000 <= ord(char) <= 0xFFFD
        or 0x10000 <= ord(char) <= 0x10FFFF
    )
    return (
        valid.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


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


def _choose_local_folder(initial: Path) -> Path | None:
    """Open the operating system's folder picker and return a selected directory."""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError as exc:  # pragma: no cover - depends on Python distribution
        raise RuntimeError(
            "The native folder picker is unavailable in this Python installation"
        ) from exc

    root = None
    try:
        root = tk.Tk()
        root.withdraw()
        try:
            root.attributes("-topmost", True)
        except tk.TclError:
            pass
        selected = filedialog.askdirectory(
            parent=root,
            initialdir=str(initial),
            mustexist=True,
            title="Choose a folder for ChatGPT context",
        )
    except tk.TclError as exc:  # pragma: no cover - depends on desktop session
        raise RuntimeError(
            "The native folder picker requires a graphical desktop session"
        ) from exc
    finally:
        if root is not None:
            root.destroy()

    if not selected:
        return None
    chosen = Path(selected).expanduser().resolve()
    if not chosen.is_dir():
        raise RuntimeError("The selected folder is not available")
    return chosen


def _build_html(access_token: str = "") -> str:
    page = Path(__file__).with_name("file_context_ui.html").read_text(encoding="utf-8")
    return page.replace("__CONSURG_ACCESS_TOKEN__", access_token)
