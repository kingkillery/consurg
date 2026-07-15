from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

SCHEMA_VERSION = "1.0"
REDACTION_ERROR_SENTINEL = "[REDACTION_ERROR]"
TRUNCATION_MARKER = "...[TRUNCATED]"
DEFAULT_MAX_STRING = 4096

_SENSITIVE_KEYS = {
    "password",
    "passwd",
    "token",
    "secret",
    "authorization",
    "api_key",
    "private_key",
    "client_secret",
}

_SECRET_PATTERNS = [
    re.compile(r"(?i)\b(authorization)\s*:\s*([^\s,;]+)"),
    re.compile(r"(?i)\b(bearer)\s+[a-z0-9\-._~+/]+=*", re.IGNORECASE),
    re.compile(r"(?i)\b(basic)\s+[a-z0-9\-._~+/]+=*", re.IGNORECASE),
    re.compile(r"\beyJ[a-zA-Z0-9_\-]{8,}\.[a-zA-Z0-9_\-]{8,}\.[a-zA-Z0-9_\-]{8,}\b"),
    re.compile(r"\bsk-[a-zA-Z0-9]{12,}\b"),
]


@dataclass
class AuditConfig:
    enabled: bool = False
    storage_path: Path = Path(".pk-agent") / "runs"
    max_runs: int = 200
    max_age_days: int = 14
    max_bytes: int = 104857600
    redaction_profile: str = "strict-v1"
    include_tool_names: list[str] = None  # type: ignore[assignment]
    exclude_tool_names: list[str] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.include_tool_names is None:
            self.include_tool_names = ["*"]
        if self.exclude_tool_names is None:
            self.exclude_tool_names = []


def load_audit_config(project_root: Path, env: dict[str, str] | None = None) -> AuditConfig:
    env = env or os.environ
    config = AuditConfig()
    config_path = project_root / ".consurg-audit.yaml"
    file_config: dict[str, Any] = {}

    if config_path.exists():
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        if isinstance(loaded, dict):
            file_config = loaded

    if "enabled" in file_config:
        config.enabled = bool(file_config["enabled"])
    if "storage_path" in file_config and isinstance(file_config["storage_path"], str):
        config.storage_path = Path(file_config["storage_path"])
    if "max_runs" in file_config:
        config.max_runs = _to_int(file_config["max_runs"], default=config.max_runs)
    if "max_age_days" in file_config:
        config.max_age_days = _to_int(file_config["max_age_days"], default=config.max_age_days)
    if "max_bytes" in file_config:
        config.max_bytes = _to_int(file_config["max_bytes"], default=config.max_bytes)
    if "redaction_profile" in file_config and isinstance(file_config["redaction_profile"], str):
        config.redaction_profile = file_config["redaction_profile"]
    if "include_tool_names" in file_config and isinstance(file_config["include_tool_names"], list):
        config.include_tool_names = [str(v) for v in file_config["include_tool_names"]]
    if "exclude_tool_names" in file_config and isinstance(file_config["exclude_tool_names"], list):
        config.exclude_tool_names = [str(v) for v in file_config["exclude_tool_names"]]

    if env.get("CONSURG_AUDIT_PERSIST") == "1":
        config.enabled = True
    if env.get("CONSURG_AUDIT_MAX_RUNS"):
        config.max_runs = _to_int(env["CONSURG_AUDIT_MAX_RUNS"], default=config.max_runs)
    if env.get("CONSURG_AUDIT_MAX_AGE_DAYS"):
        config.max_age_days = _to_int(env["CONSURG_AUDIT_MAX_AGE_DAYS"], default=config.max_age_days)
    if env.get("CONSURG_AUDIT_MAX_BYTES"):
        config.max_bytes = _to_int(env["CONSURG_AUDIT_MAX_BYTES"], default=config.max_bytes)

    if not config.storage_path.is_absolute():
        config.storage_path = project_root / config.storage_path

    return config


def should_audit_tool(tool_name: str, config: AuditConfig) -> bool:
    if not config.enabled:
        return False
    if "*" not in config.include_tool_names and tool_name not in config.include_tool_names:
        return False
    if tool_name in config.exclude_tool_names:
        return False
    return True


def persist_trace(
    config: AuditConfig,
    run_id: str,
    started_at: datetime,
    tool_calls: list[dict[str, Any]],
) -> Path:
    timestamp_dir = started_at.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = config.storage_path / timestamp_dir
    run_dir.mkdir(parents=True, exist_ok=True)

    redacted_calls = [_redact_tool_call(call) for call in tool_calls]

    payload = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "started_at": started_at.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "tool_calls": redacted_calls,
        "retention_policy_snapshot": {
            "max_runs": config.max_runs,
            "max_age_days": config.max_age_days,
            "max_bytes": config.max_bytes,
        },
    }

    trace_path = run_dir / "trace.json"
    trace_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="ascii")
    prune_runs(config)
    return trace_path


def prune_runs(config: AuditConfig, now: datetime | None = None):
    now = now or datetime.now(timezone.utc)
    config.storage_path.mkdir(parents=True, exist_ok=True)

    runs = []
    for child in config.storage_path.iterdir():
        if not child.is_dir():
            continue
        ts = _parse_run_ts(child.name)
        if ts is None:
            continue
        runs.append((child, ts))

    runs.sort(key=lambda x: x[1])

    age_cutoff = now - timedelta(days=config.max_age_days)
    remaining: list[tuple[Path, datetime]] = []
    for run_dir, ts in runs:
        if ts < age_cutoff:
            _safe_rmtree(run_dir)
        else:
            remaining.append((run_dir, ts))

    while len(remaining) > config.max_runs:
        oldest, _ = remaining.pop(0)
        _safe_rmtree(oldest)

    def _total_bytes(paths: list[tuple[Path, datetime]]) -> int:
        total = 0
        for run_dir, _ in paths:
            total += _dir_bytes(run_dir)
        return total

    while remaining and _total_bytes(remaining) > config.max_bytes:
        oldest, _ = remaining.pop(0)
        _safe_rmtree(oldest)


def audit_storage_stats(storage_path: Path) -> dict[str, int]:
    if not storage_path.exists():
        return {"runs": 0, "bytes": 0}

    runs = 0
    total_bytes = 0
    for child in storage_path.iterdir():
        if child.is_dir() and _parse_run_ts(child.name) is not None:
            runs += 1
            total_bytes += _dir_bytes(child)
    return {"runs": runs, "bytes": total_bytes}


def _to_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
        return parsed if parsed > 0 else default
    except (TypeError, ValueError):
        return default


def _parse_run_ts(name: str) -> datetime | None:
    try:
        return datetime.strptime(name, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _dir_bytes(path: Path) -> int:
    total = 0
    for p in path.rglob("*"):
        if p.is_file():
            try:
                total += p.stat().st_size
            except OSError:
                continue
    return total


def _safe_rmtree(path: Path):
    for p in sorted(path.rglob("*"), reverse=True):
        try:
            if p.is_file():
                p.unlink()
            elif p.is_dir():
                p.rmdir()
        except OSError:
            continue
    try:
        path.rmdir()
    except OSError:
        pass


def _redact_tool_call(call: dict[str, Any]) -> dict[str, Any]:
    flags: set[str] = set()
    name = _ascii_truncate(str(call.get("name", "unknown")))
    call_type = _ascii_truncate(str(call.get("type", "tool")))
    success = bool(call.get("success", False))
    start_time = _to_int(call.get("start_time"), 0)
    duration_ms = _to_int(call.get("duration_ms"), 0)

    try:
        raw_input = call.get("input")
        redacted_input = _redact_value(raw_input, flags=flags, key_hint=None)
    except Exception:
        redacted_input = REDACTION_ERROR_SENTINEL
        flags.add("redaction_error")

    try:
        raw_output = call.get("output")
        redacted_output = _redact_value(raw_output, flags=flags, key_hint=None)
    except Exception:
        redacted_output = REDACTION_ERROR_SENTINEL
        flags.add("redaction_error")

    return {
        "name": name,
        "type": call_type,
        "start_time": start_time,
        "duration_ms": duration_ms,
        "success": success,
        "redacted_input": _ascii_truncate(_stringify(redacted_input)),
        "redacted_output": _ascii_truncate(_stringify(redacted_output)),
        "redaction_flags": sorted(flags),
    }


def _redact_value(value: Any, flags: set[str], key_hint: str | None) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            key = str(k)
            if key.lower() in _SENSITIVE_KEYS:
                out[key] = "[REDACTED]"
                flags.add(f"field:{key.lower()}")
                continue
            out[key] = _redact_value(v, flags=flags, key_hint=key.lower())
        return out

    if isinstance(value, list):
        return [_redact_value(v, flags=flags, key_hint=key_hint) for v in value]

    as_text = _stringify(value)
    if key_hint and key_hint in _SENSITIVE_KEYS:
        flags.add(f"field:{key_hint}")
        return "[REDACTED]"

    redacted = as_text
    for idx, pattern in enumerate(_SECRET_PATTERNS):
        if pattern.search(redacted):
            redacted = pattern.sub("[REDACTED]", redacted)
            flags.add(f"pattern:{idx}")

    return redacted


def _stringify(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=True, sort_keys=True)
    except Exception:
        return str(value)


def _ascii_truncate(value: str, max_len: int = DEFAULT_MAX_STRING) -> str:
    clean = value.encode("ascii", "replace").decode("ascii")
    if len(clean) <= max_len:
        return clean
    return clean[: max_len - len(TRUNCATION_MARKER)] + TRUNCATION_MARKER
