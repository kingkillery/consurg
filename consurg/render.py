"""Render a scope's files into a copy-pasteable prompt.

This is the "second output" of a scope: the same tier selection that the
guard enforces on a live agent is composed here into a text blob for
pasting into ChatGPT/Claude/etc.

Tier semantics when rendering:
    T4 (read-write) / T3 (read-only)  -> full file content
    T2 (signature)                    -> extracted signatures only
    T1 (existence)                    -> listed in the file tree, no content
    T0 / unlisted                     -> omitted entirely
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass, field
from pathlib import Path

from consurg.enforce import resolve_tier
from consurg.scope import Scope, pattern_matches
from consurg.trace.signatures import extract_signatures_from_source

FORMATS = ("markdown", "plain", "xml")
HARD_MAX_FILE_BYTES = 10 * 1024 * 1024
HARD_MAX_TOTAL_BYTES = 50 * 1024 * 1024

_TIER_ACCESS_LABEL = {
    4: "read-write",
    3: "read-only",
    2: "signatures",
    1: "listed",
}

_TIER_TAG = {4: "RW", 3: "RO", 2: "SIG", 1: "--"}


@dataclass
class RenderLimits:
    """File-size guards for rendering. Any object with these attributes works."""

    never_include: list[str] = field(default_factory=list)
    max_file_bytes: int = 20000
    max_total_bytes: int = 200000


@dataclass
class ComposeResult:
    text: str = ""
    token_estimate: int = 0
    included: list[tuple[str, int]] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)


def estimate_tokens(text: str) -> int:
    """Cheap token estimate (~4 chars/token)."""
    return max(0, (len(text) + 3) // 4)


def estimate_file_tokens(path: Path) -> int:
    try:
        return max(0, (path.stat().st_size + 3) // 4)
    except OSError:
        return 0


def compose_from_scope(
    scope: Scope,
    cwd: Path,
    candidates: list[str],
    limits: RenderLimits | None = None,
    fmt: str = "markdown",
    task: str = "",
) -> ComposeResult:
    """Resolve each candidate file's tier from the scope and render."""
    tiers: dict[str, int] = {}
    for rel in candidates:
        tier, _ = resolve_tier(rel, scope)
        if tier >= 1:
            tiers[rel] = tier
    return compose_from_tiers(
        tiers,
        cwd,
        limits=limits,
        fmt=fmt,
        task=task,
        scope_name=scope.scope_name,
        reason=scope.reason,
    )


def compose_from_tiers(
    tiers: dict[str, int],
    cwd: Path,
    limits: RenderLimits | None = None,
    fmt: str = "markdown",
    task: str = "",
    scope_name: str = "",
    reason: str = "",
) -> ComposeResult:
    """Render an explicit {relative_path: tier} map into a prompt."""
    if fmt not in FORMATS:
        fmt = "markdown"
    limits = limits or RenderLimits()
    result = ComposeResult()
    max_file_bytes = _bounded_limit(
        limits.max_file_bytes, default=RenderLimits.max_file_bytes, maximum=HARD_MAX_FILE_BYTES
    )
    max_total_bytes = _bounded_limit(
        limits.max_total_bytes, default=RenderLimits.max_total_bytes, maximum=HARD_MAX_TOTAL_BYTES
    )

    ordered = sorted(
        (path.replace("\\", "/"), tier) for path, tier in tiers.items() if tier >= 1
    )
    visible: list[tuple[str, int]] = []
    for path, tier in ordered:
        if _denied(path, limits.never_include):
            result.skipped.append((path, "excluded by never_include policy"))
        elif not _path_within_root(cwd / path, cwd):
            result.skipped.append((path, "outside project root"))
        else:
            visible.append((path, tier))

    blocks: list[str] = [_header(scope_name, reason, task, fmt)]
    if visible:
        blocks.append(_tree_block(visible, fmt))

    total_bytes = 0
    for rel, tier in visible:
        if tier == 1:
            result.included.append((rel, tier))
            continue

        body, reason_skipped = _file_body(cwd / rel, tier, limits, cwd, max_file_bytes)
        if reason_skipped:
            result.skipped.append((rel, reason_skipped))
            continue

        block = _content_block(rel, tier, body, fmt)
        size = len(block.encode("utf-8"))
        if total_bytes + size > max_total_bytes:
            result.skipped.append((rel, "total size limit reached"))
            continue
        blocks.append(block)
        total_bytes += size
        result.included.append((rel, tier))

    if result.skipped:
        blocks.append(_skipped_block(result.skipped, fmt))

    if fmt == "xml":
        blocks.append("</context>")

    result.text = "\n".join(b for b in blocks if b).rstrip() + "\n"
    result.token_estimate = estimate_tokens(result.text)
    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _denied(path: str, patterns: list[str]) -> bool:
    normalized = path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return any(
        pattern_matches(normalized, str(p).replace("\\", "/").strip())
        for p in patterns
        if str(p).strip()
    )


def _path_within_root(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except (OSError, RuntimeError, ValueError):
        return False


def _header(scope_name: str, reason: str, task: str, fmt: str) -> str:
    lines: list[str] = []
    title = scope_name or "repository context"
    if fmt == "xml":
        lines.append(f'<context name="{_xml_escape(title)}">')
        if reason:
            lines.append(f"<reason>{_xml_escape(reason)}</reason>")
        if task:
            lines.append(f"<task>{_xml_escape(task)}</task>")
    elif fmt == "plain":
        lines.append(f"CONTEXT: {title}")
        if reason:
            lines.append(f"Reason: {reason}")
        if task:
            lines.append("")
            lines.append(f"TASK: {task}")
        lines.append("")
    else:
        lines.append(f"# Context: {title}")
        if reason:
            lines.append(f"> {reason}")
        if task:
            lines.append("")
            lines.append("## Task")
            lines.append(task)
        lines.append("")
    return "\n".join(lines)


def _tree_block(visible: list[tuple[str, int]], fmt: str) -> str:
    if fmt == "xml":
        rows = [
            f'<file path="{_xml_escape(path)}" tier="{_TIER_TAG.get(tier, "?")}" />'
            for path, tier in visible
        ]
        tree = "\n".join(rows)
        return f"<file_tree>\n{tree}\n</file_tree>\n"
    rows = [f"{path}  [{_TIER_TAG.get(tier, '?')}]" for path, tier in visible]
    tree = "\n".join(rows)
    if fmt == "plain":
        return f"FILES ({len(rows)}):\n{tree}\n"
    return f"## Files\n```\n{tree}\n```\n"


def _bounded_limit(value: object, *, default: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    if parsed <= 0:
        return default
    return min(parsed, maximum)


def safe_read_context_file(
    full_path: Path, root: Path, max_file_bytes: int
) -> tuple[str | None, str | None]:
    """Read a project file without following unsafe path components.

    The component snapshots make a rename/symlink swap detectable on platforms
    where a descriptor-relative walk is unavailable (notably Windows).
    """
    try:
        root_path = Path(os.path.abspath(root))
        path = Path(os.path.abspath(full_path))
        relative = path.relative_to(root_path)
    except (OSError, RuntimeError, ValueError):
        return None, "outside project root"
    if ".." in relative.parts:
        return None, "outside project root"
    try:
        before = _path_component_identities(root_path, relative)
    except FileNotFoundError:
        return None, "file not found"
    except ValueError:
        return None, "symlink or reparse point"
    except (OSError, RuntimeError):
        return None, "unreadable"

    limit = _bounded_limit(
        max_file_bytes, default=RenderLimits.max_file_bytes, maximum=HARD_MAX_FILE_BYTES
    )
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(path, flags)
    except FileNotFoundError:
        return None, "file not found"
    except OSError:
        return None, "unreadable"

    try:
        with os.fdopen(fd, "rb", closefd=True) as source:
            opened = os.fstat(source.fileno())
            payload = source.read(limit + 1)
    except OSError:
        return None, "unreadable"
    try:
        after = _path_component_identities(root_path, relative)
    except (OSError, RuntimeError, ValueError):
        return None, "path changed during read"

    if before != after or _file_identity(opened) != before[-1][1]:
        return None, "path changed during read"
    if len(payload) > limit:
        return None, "exceeds max_file_bytes"
    if b"\x00" in payload:
        return None, "binary file"
    try:
        return payload.decode("utf-8"), None
    except UnicodeDecodeError:
        return None, "binary file"


def _path_component_identities(
    root: Path, relative: Path
) -> list[tuple[Path, tuple[int, int]]]:
    """Snapshot every component, rejecting links and Windows reparse points."""
    current = root
    snapshots: list[tuple[Path, tuple[int, int]]] = []
    for component in (".", *relative.parts):
        if component != ".":
            current /= component
        entry = os.lstat(current)
        if stat.S_ISLNK(entry.st_mode) or _is_reparse_point(entry):
            raise ValueError("symlink or reparse point")
        snapshots.append((current, _file_identity(entry)))
    return snapshots


def _file_identity(entry: os.stat_result) -> tuple[int, int]:
    return entry.st_dev, entry.st_ino


def _is_reparse_point(entry: os.stat_result) -> bool:
    attributes = getattr(entry, "st_file_attributes", 0)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & reparse)


def _file_body(
    full_path: Path,
    tier: int,
    limits: RenderLimits,
    root: Path,
    max_file_bytes: int | None = None,
) -> tuple[str, str | None]:
    """Return safely-read content or signatures extracted from that content."""
    file_limit = max_file_bytes or _bounded_limit(
        limits.max_file_bytes, default=RenderLimits.max_file_bytes, maximum=HARD_MAX_FILE_BYTES
    )
    source, skipped = safe_read_context_file(full_path, root, file_limit)
    if skipped:
        return "", skipped
    assert source is not None
    if tier == 2:
        sigs = extract_signatures_from_source(source, full_path.suffix)
        if sigs:
            return "\n".join(sigs), None
        return "[no extractable signatures]", None
    return source, None


def _content_block(rel: str, tier: int, body: str, fmt: str) -> str:
    access = _TIER_ACCESS_LABEL.get(tier, "read-only")
    if fmt == "xml":
        tag = "signatures" if tier == 2 else "file"
        return (
            f'<{tag} path="{_xml_escape(rel)}" access="{access}">\n'
            f"{_xml_escape(body)}\n</{tag}>\n"
        )
    if fmt == "plain":
        label = "SIGNATURES" if tier == 2 else "FILE"
        underline = "-" * max(3, len(rel))
        return f"{label}: {rel} ({access})\n{underline}\n{body}\n"
    lang = Path(rel).suffix.lower().lstrip(".")
    label = "SIGNATURES" if tier == 2 else "FILE"
    return f"## {label}: {rel} ({access})\n```{lang}\n{body}\n```\n"


def _skipped_block(skipped: list[tuple[str, str]], fmt: str) -> str:
    rows = [f"{p}: {why}" for p, why in skipped]
    body = "\n".join(rows)
    if fmt == "xml":
        return f"<omitted>\n{_xml_escape(body)}\n</omitted>\n"
    if fmt == "plain":
        return f"OMITTED:\n{body}\n"
    return f"## Omitted\n```\n{body}\n```\n"


def _xml_escape(text: str) -> str:
    text = "".join(char for char in text if _is_xml_1_0_character(char))
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _is_xml_1_0_character(char: str) -> bool:
    codepoint = ord(char)
    return (
        codepoint in (0x9, 0xA, 0xD)
        or 0x20 <= codepoint <= 0xD7FF
        or 0xE000 <= codepoint <= 0xFFFD
        or 0x10000 <= codepoint <= 0x10FFFF
    )
