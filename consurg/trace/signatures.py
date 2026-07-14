import re
from pathlib import Path

# Python patterns
_PY_DEF = re.compile(r"^(\s*)(async\s+)?def\s+(\w+)\s*\(([^)]*)\)\s*", re.MULTILINE)
_PY_CLASS = re.compile(r"^(\s*)class\s+(\w+)(?:\s*\(([^)]*)\))?\s*:", re.MULTILINE)

# TS/JS patterns
_TS_FUNCTION = re.compile(
    r"^(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*(?:<[^>]*>)?\s*\(([^)]*)\)",
    re.MULTILINE,
)
_TS_CLASS = re.compile(
    r"^(?:export\s+)?(?:abstract\s+)?class\s+(\w+)", re.MULTILINE
)
_TS_INTERFACE = re.compile(
    r"^(?:export\s+)?interface\s+(\w+)", re.MULTILINE
)
_TS_TYPE = re.compile(
    r"^(?:export\s+)?type\s+(\w+)\s*(?:<[^>]*>)?\s*=", re.MULTILINE
)
_TS_ARROW = re.compile(
    r"^(?:export\s+)?(?:const|let|var)\s+(\w+)\s*(?::\s*[^=]+)?\s*=\s*(?:async\s+)?(?:\([^)]*\)|[^=])\s*=>",
    re.MULTILINE,
)

_PY_EXTENSIONS = {".py", ".pyi"}
_TS_EXTENSIONS = {".ts", ".tsx", ".js", ".jsx", ".mts", ".mjs"}


def extract_signatures(file_path: str, max_file_bytes: int = 20000) -> list[str]:
    """Extract signatures from a bounded UTF-8 source file (legacy API)."""
    path = Path(file_path)
    try:
        limit = max(0, int(max_file_bytes))
        with path.open("rb") as source_file:
            payload = source_file.read(limit + 1)
        if len(payload) > limit:
            return []
        source = payload.decode("utf-8")
    except (OSError, UnicodeDecodeError, TypeError, ValueError):
        return []
    return extract_signatures_from_source(source, path.suffix)


def extract_signatures_from_source(source: str, suffix: str) -> list[str]:
    """Extract signatures from already-read source without reopening its path."""
    suffix = suffix.lower()
    if suffix in _PY_EXTENSIONS:
        return _extract_python(source)
    if suffix in _TS_EXTENSIONS:
        return _extract_ts(source)
    return []


def _extract_python(source: str) -> list[str]:
    sigs: list[str] = []

    for m in _PY_CLASS.finditer(source):
        name = m.group(2)
        bases = m.group(3)
        if bases:
            sigs.append(f"class {name}({bases.strip()}):")
        else:
            sigs.append(f"class {name}:")

    for m in _PY_DEF.finditer(source):
        is_async = m.group(2)
        name = m.group(3)
        args = m.group(4).strip()
        prefix = "async def" if is_async else "def"
        sigs.append(f"{prefix} {name}({args}):")

    return sigs


def _extract_ts(source: str) -> list[str]:
    sigs: list[str] = []

    for m in _TS_CLASS.finditer(source):
        sigs.append(f"class {m.group(1)}")

    for m in _TS_INTERFACE.finditer(source):
        sigs.append(f"interface {m.group(1)}")

    for m in _TS_TYPE.finditer(source):
        sigs.append(f"type {m.group(1)}")

    for m in _TS_FUNCTION.finditer(source):
        name = m.group(1)
        args = m.group(2).strip()
        sigs.append(f"function {name}({args})")

    return sigs
