import json
import re
from pathlib import Path

from consurg.trace.graph import DependencyKind

# Patterns for TS/JS imports
_IMPORT_FROM = re.compile(
    r"""(?:import\s+(?:type\s+)?(?:[\w{}\s,*]+)\s+from\s+['"]([^'"]+)['"])"""
)
_REQUIRE = re.compile(r"""require\(\s*['"]([^'"]+)['"]\s*\)""")
_DYNAMIC_IMPORT = re.compile(r"""import\(\s*['"]([^'"]+)['"]\s*\)""")
_EXPORT_FROM = re.compile(r"""export\s+(?:\*|{[^}]*})\s+from\s+['"]([^'"]+)['"]""")
_IMPORT_TYPE = re.compile(r"""import\s+type\s+""")

_TS_EXTENSIONS = [".ts", ".tsx", ".js", ".jsx", ".mts", ".mjs"]


def resolve_ts_imports(
    file_path: str, project_root: str
) -> list[tuple[str, DependencyKind]]:
    root = Path(project_root)
    source_path = Path(file_path)

    try:
        source = source_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    tsconfig_paths, base_url = _load_tsconfig(root)
    results: list[tuple[str, DependencyKind]] = []

    for line in source.splitlines():
        stripped = line.strip()

        # export ... from '...'
        m = _EXPORT_FROM.search(stripped)
        if m:
            resolved = _resolve_specifier(m.group(1), source_path, root, tsconfig_paths, base_url)
            if resolved:
                results.append((resolved, DependencyKind.RE_EXPORT))
            continue

        # import type
        is_type_only = bool(_IMPORT_TYPE.search(stripped))

        # import ... from '...'
        m = _IMPORT_FROM.search(stripped)
        if m:
            resolved = _resolve_specifier(m.group(1), source_path, root, tsconfig_paths, base_url)
            if resolved:
                kind = DependencyKind.TYPE_ONLY if is_type_only else DependencyKind.IMPORT
                results.append((resolved, kind))
            continue

        # require('...')
        m = _REQUIRE.search(stripped)
        if m:
            resolved = _resolve_specifier(m.group(1), source_path, root, tsconfig_paths, base_url)
            if resolved:
                results.append((resolved, DependencyKind.IMPORT))
            continue

        # import('...')
        m = _DYNAMIC_IMPORT.search(stripped)
        if m:
            resolved = _resolve_specifier(m.group(1), source_path, root, tsconfig_paths, base_url)
            if resolved:
                results.append((resolved, DependencyKind.IMPORT))
            continue

    return results


def _resolve_specifier(
    specifier: str,
    source_path: Path,
    root: Path,
    tsconfig_paths: dict[str, list[str]],
    base_url: str | None,
) -> str | None:
    # Skip bare module specifiers (node_modules)
    if not specifier.startswith(".") and not specifier.startswith("/"):
        # Check tsconfig paths
        resolved = _try_tsconfig_paths(specifier, root, tsconfig_paths, base_url)
        if resolved:
            return resolved
        # Check baseUrl
        if base_url:
            resolved = _try_resolve_file(root / base_url / specifier, root)
            if resolved:
                return resolved
        return None

    # Relative import
    if specifier.startswith("."):
        target = source_path.parent / specifier
    else:
        target = root / specifier.lstrip("/")

    return _try_resolve_file(target, root)


def _try_resolve_file(target: Path, root: Path) -> str | None:
    # Exact match (already has extension)
    if target.suffix and target.exists():
        try:
            return str(target.relative_to(root)).replace("\\", "/")
        except ValueError:
            return None

    # Try adding extensions
    for ext in _TS_EXTENSIONS:
        candidate = target.with_suffix(ext)
        if candidate.exists():
            try:
                return str(candidate.relative_to(root)).replace("\\", "/")
            except ValueError:
                return None

    # Try as directory with index file
    if target.is_dir():
        for ext in _TS_EXTENSIONS:
            index = target / f"index{ext}"
            if index.exists():
                try:
                    return str(index.relative_to(root)).replace("\\", "/")
                except ValueError:
                    return None

    return None


def _try_tsconfig_paths(
    specifier: str,
    root: Path,
    paths: dict[str, list[str]],
    base_url: str | None,
) -> str | None:
    for pattern, mappings in paths.items():
        # Handle exact match patterns (no wildcard)
        if "*" not in pattern:
            if specifier == pattern:
                for mapping in mappings:
                    base = root / base_url if base_url else root
                    resolved = _try_resolve_file(base / mapping, root)
                    if resolved:
                        return resolved
            continue

        # Handle wildcard patterns like "@/*"
        prefix = pattern.split("*")[0]
        if specifier.startswith(prefix):
            rest = specifier[len(prefix):]
            for mapping in mappings:
                replaced = mapping.replace("*", rest)
                base = root / base_url if base_url else root
                resolved = _try_resolve_file(base / replaced, root)
                if resolved:
                    return resolved

    return None


def _load_tsconfig(root: Path) -> tuple[dict[str, list[str]], str | None]:
    tsconfig_path = root / "tsconfig.json"
    if not tsconfig_path.exists():
        return {}, None

    try:
        # Strip comments (basic single-line comment removal)
        text = tsconfig_path.read_text(encoding="utf-8")
        text = re.sub(r"//.*$", "", text, flags=re.MULTILINE)
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
        data = json.loads(text)
    except (json.JSONDecodeError, OSError):
        return {}, None

    compiler_options = data.get("compilerOptions", {})
    base_url = compiler_options.get("baseUrl")
    paths = compiler_options.get("paths", {})

    return paths, base_url
