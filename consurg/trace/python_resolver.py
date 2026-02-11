import ast
from pathlib import Path

from consurg.trace.graph import DependencyKind


def resolve_python_imports(
    file_path: str, project_root: str
) -> list[tuple[str, DependencyKind]]:
    root = Path(project_root)
    source_path = Path(file_path)

    try:
        source = source_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    try:
        tree = ast.parse(source, filename=str(source_path))
    except SyntaxError:
        return []

    results: list[tuple[str, DependencyKind]] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                resolved = _resolve_absolute(alias.name, root)
                if resolved:
                    results.append((resolved, DependencyKind.IMPORT))

        elif isinstance(node, ast.ImportFrom):
            if node.level > 0:
                # Relative import
                if node.module:
                    # from .module import X -> resolve module
                    resolved = _resolve_relative(
                        node.module, node.level, source_path, root
                    )
                    if resolved:
                        results.append((resolved, DependencyKind.IMPORT))
                else:
                    # from . import X, Y -> resolve each name as submodule
                    base = source_path.parent
                    for _ in range(node.level - 1):
                        base = base.parent
                    for alias in node.names:
                        resolved = _resolve_relative(
                            alias.name, node.level, source_path, root
                        )
                        if resolved:
                            results.append((resolved, DependencyKind.IMPORT))
            else:
                resolved = _resolve_absolute(node.module or "", root)
                if resolved:
                    results.append((resolved, DependencyKind.IMPORT))

    return results


def _resolve_absolute(module_name: str, root: Path) -> str | None:
    parts = module_name.split(".")
    # Try as a module file: a/b/c.py
    module_path = root / Path(*parts)
    py_file = module_path.with_suffix(".py")
    if py_file.exists():
        return str(py_file.relative_to(root)).replace("\\", "/")

    # Try as a package: a/b/c/__init__.py
    init_file = module_path / "__init__.py"
    if init_file.exists():
        return str(init_file.relative_to(root)).replace("\\", "/")

    return None


def _resolve_relative(
    module: str | None, level: int, source_path: Path, root: Path
) -> str | None:
    # Start from the directory containing the source file
    base = source_path.parent

    # Go up (level - 1) directories (level=1 means current package)
    for _ in range(level - 1):
        base = base.parent

    if module:
        parts = module.split(".")
        target = base / Path(*parts)
    else:
        target = base

    # Try as module file
    py_file = target.with_suffix(".py")
    if py_file.exists():
        try:
            return str(py_file.relative_to(root)).replace("\\", "/")
        except ValueError:
            return None

    # Try as package
    init_file = target / "__init__.py"
    if init_file.exists():
        try:
            return str(init_file.relative_to(root)).replace("\\", "/")
        except ValueError:
            return None

    return None
