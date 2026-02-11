# Trace Engine Reference

The trace engine auto-builds scopes by analyzing import dependencies or git diffs.

## Trace Command

```bash
consurg trace <entry_files> [--depth N] [--apply]
```

### Tier Classification by Distance

| Distance from Entry | Tier | Scope Key |
|---------------------|------|-----------|
| 0 (entry file) | T4 | `working_set` |
| 1 (direct dependency) | T3 | `reference` |
| 2+ (transitive) | T2 | `signatures` |
| In graph but unreachable | T1 | `visible` |

### Multiple Entry Points

```bash
consurg trace src/auth/login.py src/auth/register.py --depth 3 --apply
```

All entry files get T4. Combined dependency graphs are merged.

## Python Import Resolution

Uses `ast.walk()` for accurate parsing:

- `import foo` -- resolves `foo.py` or `foo/__init__.py`
- `from foo import bar` -- resolves `foo.py` or `foo/bar.py`
- `from . import sibling` -- relative imports resolved against package
- `from ..parent import module` -- multi-level relative imports
- Package imports with `__init__.py`
- Multiple imports per line

## TypeScript/JavaScript Import Resolution

Uses regex-based line parsing:

- `import { x } from './module'`
- `import x from './module'`
- `export { x } from './module'`
- `const x = require('./module')`
- `const x = await import('./module')` (dynamic)
- `import type { T } from './types'` (marked TYPE_ONLY)

Handles:
- Extension resolution: `.ts`, `.tsx`, `.js`, `.jsx`, `.mts`, `.mjs`
- Index file resolution: `./dir` resolves to `./dir/index.ts`
- `tsconfig.json` path aliases and `baseUrl` mapping
- Named re-exports

## Git Diff Command

```bash
consurg git-diff [base_branch] [--apply]
```

1. Runs `git diff --name-only <base>...HEAD`
2. Changed files get T4 (working_set)
3. Direct dependencies of changed files get T3 (reference)
4. Auto-detects `main` or `master` if no base specified

## Dependency Graph API

```python
from consurg.trace import DependencyGraph, resolve_python_imports

graph = DependencyGraph()

# Add edges via resolvers
deps = resolve_python_imports("src/auth/login.py", project_root)
for dep_path, kind in deps:
    graph.add_edge("src/auth/login.py", dep_path, kind)

# Classify into tiers
tiers = graph.classify_tiers(["src/auth/login.py"])
# {"src/auth/login.py": 4, "src/core/db.py": 3, "src/utils/crypto.py": 2}
```

### Dependency Kinds

| Kind | Meaning |
|------|---------|
| `IMPORT` | Standard import dependency |
| `RE_EXPORT` | TypeScript named re-export (`export { x } from './module'`) |
| `TYPE_ONLY` | TypeScript `import type` (no runtime effect) |

### BFS Classification Algorithm

```python
def classify_tiers(self, entry_files: list[str]) -> dict[str, int]:
    # Entry files -> T4
    # BFS from entries: direct deps -> T3
    # BFS from direct deps: transitive deps -> T2
    # Everything else in graph -> T1
```

## Signature Extraction

```python
from consurg.trace.signatures import extract_signatures

sigs = extract_signatures("src/auth/login.py")
# ["def authenticate(username: str, password: str) -> User:",
#  "class AuthManager:"]
```

Supported:
- **Python:** `def`, `async def`, `class` (with base classes)
- **TypeScript:** `function`, `class`, `interface`, `type`, arrow functions
