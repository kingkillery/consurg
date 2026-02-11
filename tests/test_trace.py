from pathlib import Path

import pytest

from consurg.trace.graph import DependencyGraph, DependencyKind
from consurg.trace.python_resolver import resolve_python_imports
from consurg.trace.ts_resolver import resolve_ts_imports
from consurg.trace.signatures import extract_signatures


# ── Python import resolution ──────────────────────────────────────────


def test_python_absolute_import(tmp_path):
    (tmp_path / "foo").mkdir()
    (tmp_path / "foo" / "__init__.py").write_text("")
    (tmp_path / "foo" / "bar.py").write_text("")
    entry = tmp_path / "main.py"
    entry.write_text("import foo.bar\n")

    result = resolve_python_imports(str(entry), str(tmp_path))
    assert len(result) == 1
    assert result[0] == ("foo/bar.py", DependencyKind.IMPORT)


def test_python_from_import(tmp_path):
    (tmp_path / "utils.py").write_text("")
    entry = tmp_path / "main.py"
    entry.write_text("from utils import helper\n")

    result = resolve_python_imports(str(entry), str(tmp_path))
    assert len(result) == 1
    assert result[0] == ("utils.py", DependencyKind.IMPORT)


def test_python_relative_import(tmp_path):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "sibling.py").write_text("")
    entry = pkg / "main.py"
    entry.write_text("from . import sibling\n")

    result = resolve_python_imports(str(entry), str(tmp_path))
    assert len(result) == 1
    assert result[0] == ("pkg/sibling.py", DependencyKind.IMPORT)


def test_python_relative_parent_import(tmp_path):
    pkg = tmp_path / "pkg"
    sub = pkg / "sub"
    sub.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (sub / "__init__.py").write_text("")
    (pkg / "util.py").write_text("")
    entry = sub / "main.py"
    entry.write_text("from .. import util\n")

    result = resolve_python_imports(str(entry), str(tmp_path))
    assert len(result) == 1
    assert result[0] == ("pkg/util.py", DependencyKind.IMPORT)


def test_python_package_import(tmp_path):
    pkg = tmp_path / "mypkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    entry = tmp_path / "main.py"
    entry.write_text("import mypkg\n")

    result = resolve_python_imports(str(entry), str(tmp_path))
    assert len(result) == 1
    assert result[0] == ("mypkg/__init__.py", DependencyKind.IMPORT)


def test_python_unresolvable_import(tmp_path):
    entry = tmp_path / "main.py"
    entry.write_text("import nonexistent\n")

    result = resolve_python_imports(str(entry), str(tmp_path))
    assert result == []


def test_python_syntax_error(tmp_path):
    entry = tmp_path / "bad.py"
    entry.write_text("def foo(:\n")

    result = resolve_python_imports(str(entry), str(tmp_path))
    assert result == []


def test_python_multiple_imports(tmp_path):
    (tmp_path / "a.py").write_text("")
    (tmp_path / "b.py").write_text("")
    entry = tmp_path / "main.py"
    entry.write_text("import a\nimport b\n")

    result = resolve_python_imports(str(entry), str(tmp_path))
    assert len(result) == 2
    paths = {r[0] for r in result}
    assert paths == {"a.py", "b.py"}


# ── TypeScript import resolution ──────────────────────────────────────


def test_ts_import_from(tmp_path):
    (tmp_path / "utils.ts").write_text("")
    entry = tmp_path / "main.ts"
    entry.write_text("import { foo } from './utils';\n")

    result = resolve_ts_imports(str(entry), str(tmp_path))
    assert len(result) == 1
    assert result[0] == ("utils.ts", DependencyKind.IMPORT)


def test_ts_require(tmp_path):
    (tmp_path / "config.js").write_text("")
    entry = tmp_path / "main.ts"
    entry.write_text("const cfg = require('./config');\n")

    result = resolve_ts_imports(str(entry), str(tmp_path))
    assert len(result) == 1
    assert result[0] == ("config.js", DependencyKind.IMPORT)


def test_ts_dynamic_import(tmp_path):
    (tmp_path / "lazy.ts").write_text("")
    entry = tmp_path / "main.ts"
    entry.write_text("const mod = import('./lazy');\n")

    result = resolve_ts_imports(str(entry), str(tmp_path))
    assert len(result) == 1
    assert result[0] == ("lazy.ts", DependencyKind.IMPORT)


def test_ts_re_export(tmp_path):
    (tmp_path / "types.ts").write_text("")
    entry = tmp_path / "index.ts"
    entry.write_text("export * from './types';\n")

    result = resolve_ts_imports(str(entry), str(tmp_path))
    assert len(result) == 1
    assert result[0] == ("types.ts", DependencyKind.RE_EXPORT)


def test_ts_type_import(tmp_path):
    (tmp_path / "types.ts").write_text("")
    entry = tmp_path / "main.ts"
    entry.write_text("import type { Foo } from './types';\n")

    result = resolve_ts_imports(str(entry), str(tmp_path))
    assert len(result) == 1
    assert result[0] == ("types.ts", DependencyKind.TYPE_ONLY)


def test_ts_index_resolution(tmp_path):
    sub = tmp_path / "components"
    sub.mkdir()
    (sub / "index.ts").write_text("")
    entry = tmp_path / "main.ts"
    entry.write_text("import { Button } from './components';\n")

    result = resolve_ts_imports(str(entry), str(tmp_path))
    assert len(result) == 1
    assert result[0] == ("components/index.ts", DependencyKind.IMPORT)


def test_ts_extension_resolution(tmp_path):
    (tmp_path / "helper.tsx").write_text("")
    entry = tmp_path / "main.ts"
    entry.write_text("import { Widget } from './helper';\n")

    result = resolve_ts_imports(str(entry), str(tmp_path))
    assert len(result) == 1
    assert result[0] == ("helper.tsx", DependencyKind.IMPORT)


def test_ts_bare_specifier_skipped(tmp_path):
    entry = tmp_path / "main.ts"
    entry.write_text("import React from 'react';\n")

    result = resolve_ts_imports(str(entry), str(tmp_path))
    assert result == []


def test_ts_tsconfig_paths(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "utils.ts").write_text("")

    tsconfig = tmp_path / "tsconfig.json"
    tsconfig.write_text(
        '{"compilerOptions": {"baseUrl": ".", "paths": {"@/*": ["src/*"]}}}'
    )

    entry = tmp_path / "main.ts"
    entry.write_text("import { foo } from '@/utils';\n")

    result = resolve_ts_imports(str(entry), str(tmp_path))
    assert len(result) == 1
    assert result[0] == ("src/utils.ts", DependencyKind.IMPORT)


def test_ts_tsconfig_base_url(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "helpers.ts").write_text("")

    tsconfig = tmp_path / "tsconfig.json"
    tsconfig.write_text('{"compilerOptions": {"baseUrl": "src"}}')

    entry = tmp_path / "main.ts"
    entry.write_text("import { foo } from 'helpers';\n")

    result = resolve_ts_imports(str(entry), str(tmp_path))
    assert len(result) == 1
    assert result[0] == ("src/helpers.ts", DependencyKind.IMPORT)


def test_ts_named_re_export(tmp_path):
    (tmp_path / "models.ts").write_text("")
    entry = tmp_path / "index.ts"
    entry.write_text("export { User, Post } from './models';\n")

    result = resolve_ts_imports(str(entry), str(tmp_path))
    assert len(result) == 1
    assert result[0] == ("models.ts", DependencyKind.RE_EXPORT)


# ── Dependency graph ──────────────────────────────────────────────────


def test_graph_add_and_query():
    g = DependencyGraph()
    g.add_edge("a.py", "b.py", DependencyKind.IMPORT)
    g.add_edge("a.py", "c.py", DependencyKind.IMPORT)

    assert g.get_dependencies("a.py") == {"b.py", "c.py"}
    assert g.get_dependents("b.py") == {"a.py"}
    assert g.get_dependents("a.py") == set()
    assert g.get_dependencies("b.py") == set()


def test_graph_classify_tiers_simple():
    g = DependencyGraph()
    g.add_edge("app.py", "lib.py", DependencyKind.IMPORT)
    g.add_edge("lib.py", "util.py", DependencyKind.IMPORT)
    g.add_edge("other.py", "unrelated.py", DependencyKind.IMPORT)

    tiers = g.classify_tiers(["app.py"])

    assert tiers["app.py"] == 4      # entry
    assert tiers["lib.py"] == 3      # direct dep
    assert tiers["util.py"] == 2     # transitive dep
    assert tiers["other.py"] == 1    # in graph, not reachable
    assert tiers["unrelated.py"] == 1


def test_graph_classify_tiers_deep_chain():
    g = DependencyGraph()
    g.add_edge("a.py", "b.py", DependencyKind.IMPORT)
    g.add_edge("b.py", "c.py", DependencyKind.IMPORT)
    g.add_edge("c.py", "d.py", DependencyKind.IMPORT)

    tiers = g.classify_tiers(["a.py"])

    assert tiers["a.py"] == 4
    assert tiers["b.py"] == 3
    assert tiers["c.py"] == 2
    assert tiers["d.py"] == 2  # transitive, depth >= 2


def test_graph_classify_tiers_multiple_entries():
    g = DependencyGraph()
    g.add_edge("main.py", "shared.py", DependencyKind.IMPORT)
    g.add_edge("test.py", "shared.py", DependencyKind.IMPORT)
    g.add_edge("shared.py", "deep.py", DependencyKind.IMPORT)

    tiers = g.classify_tiers(["main.py", "test.py"])

    assert tiers["main.py"] == 4
    assert tiers["test.py"] == 4
    assert tiers["shared.py"] == 3
    assert tiers["deep.py"] == 2


def test_graph_classify_tiers_empty_graph():
    g = DependencyGraph()
    tiers = g.classify_tiers(["nonexistent.py"])
    assert tiers == {}


def test_graph_classify_tiers_no_deps():
    g = DependencyGraph()
    g.add_edge("a.py", "b.py", DependencyKind.IMPORT)

    tiers = g.classify_tiers(["a.py"])
    assert tiers["a.py"] == 4
    assert tiers["b.py"] == 3


# ── Signature extraction ─────────────────────────────────────────────


def test_python_signatures(tmp_path):
    p = tmp_path / "example.py"
    p.write_text(
        "class MyClass:\n"
        "    pass\n"
        "\n"
        "def my_func(a, b):\n"
        "    pass\n"
        "\n"
        "async def my_async(x):\n"
        "    pass\n"
    )

    sigs = extract_signatures(str(p))
    assert "class MyClass:" in sigs
    assert "def my_func(a, b):" in sigs
    assert "async def my_async(x):" in sigs


def test_python_class_with_bases(tmp_path):
    p = tmp_path / "example.py"
    p.write_text("class Child(Parent, Mixin):\n    pass\n")

    sigs = extract_signatures(str(p))
    assert "class Child(Parent, Mixin):" in sigs


def test_ts_signatures(tmp_path):
    p = tmp_path / "example.ts"
    p.write_text(
        "export function greet(name: string): void {\n"
        "}\n"
        "\n"
        "export class UserService {\n"
        "}\n"
        "\n"
        "export interface Config {\n"
        "}\n"
        "\n"
        "export type ID = string;\n"
    )

    sigs = extract_signatures(str(p))
    assert "function greet(name: string)" in sigs
    assert "class UserService" in sigs
    assert "interface Config" in sigs
    assert "type ID" in sigs


def test_ts_non_exported_signatures(tmp_path):
    p = tmp_path / "internal.ts"
    p.write_text(
        "function helper(x: number): number {\n"
        "  return x;\n"
        "}\n"
        "\n"
        "class InternalService {\n"
        "}\n"
    )

    sigs = extract_signatures(str(p))
    assert "function helper(x: number)" in sigs
    assert "class InternalService" in sigs


def test_signatures_unknown_extension(tmp_path):
    p = tmp_path / "data.json"
    p.write_text('{"key": "value"}')

    sigs = extract_signatures(str(p))
    assert sigs == []


def test_signatures_missing_file():
    sigs = extract_signatures("/nonexistent/path/file.py")
    assert sigs == []
