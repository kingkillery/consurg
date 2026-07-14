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

from dataclasses import dataclass, field
from pathlib import Path

from consurg.enforce import resolve_tier
from consurg.scope import Scope, pattern_matches
from consurg.trace.signatures import extract_signatures

FORMATS = ("markdown", "plain", "xml")

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

    ordered = sorted(
        (p.replace("\\", "/"), t) for p, t in tiers.items() if t >= 1
    )
    visible = [(p, t) for p, t in ordered if not _denied(p, limits.never_include)]
    for p, t in ordered:
        if _denied(p, limits.never_include):
            result.skipped.append((p, "excluded by never_include policy"))

    blocks: list[str] = [_header(scope_name, reason, task, fmt)]
    if visible:
        blocks.append(_tree_block(visible, fmt))

    total_bytes = 0
    for rel, tier in visible:
        if tier == 1:
            result.included.append((rel, tier))
            continue

        body, reason_skipped = _file_body(cwd / rel, tier, limits)
        if reason_skipped:
            result.skipped.append((rel, reason_skipped))
            continue

        block = _content_block(rel, tier, body, fmt)
        size = len(block.encode("utf-8"))
        if total_bytes + size > limits.max_total_bytes:
            result.skipped.append((rel, "total size limit reached"))
            continue
        blocks.append(block)
        total_bytes += size
        result.included.append((rel, tier))

    if result.skipped:
        blocks.append(_skipped_block(result.skipped, fmt))

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
    rows = [f"{p}  [{_TIER_TAG.get(t, '?')}]" for p, t in visible]
    tree = "\n".join(rows)
    if fmt == "xml":
        return f"<file_tree>\n{tree}\n</file_tree>\n"
    if fmt == "plain":
        return f"FILES ({len(rows)}):\n{tree}\n"
    return f"## Files\n```\n{tree}\n```\n"


def _file_body(
    full_path: Path, tier: int, limits: RenderLimits
) -> tuple[str, str | None]:
    """Return (body, skip_reason). Signature tier extracts instead of reading."""
    if not full_path.exists():
        return "", "file not found"

    if tier == 2:
        sigs = extract_signatures(str(full_path))
        if sigs:
            return "\n".join(sigs), None
        return "[no extractable signatures]", None

    try:
        if full_path.stat().st_size > limits.max_file_bytes:
            return "", "exceeds max_file_bytes"
        with full_path.open("rb") as f:
            if b"\x00" in f.read(8192):
                return "", "binary file"
        return full_path.read_text(encoding="utf-8", errors="replace"), None
    except OSError:
        return "", "unreadable"


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
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )
