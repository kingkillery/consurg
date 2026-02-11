# Dependency Tracing

Context Surgeon can automatically build scopes by tracing import dependencies or analyzing git diffs.

## Trace Command

```bash
consurg trace <entry_files> [--depth N] [--apply]
```

### How It Works

1. Parses the entry files to find their imports
2. Resolves each import to a file path
3. Recursively traces imports up to `--depth` levels (default: 3)
4. Classifies files into tiers based on distance from the entry points

### Tier Classification

| Distance from Entry | Tier | Label |
|---------------------|------|-------|
| 0 (entry file itself) | T4 | working_set |
| 1 (direct dependency) | T3 | reference |
| 2+ (transitive dependency) | T2 | signatures |
| Not reachable | T1 | visible (if in graph) |

### Example

```bash
consurg trace src/auth/login.py --depth 2
```

Output:
```
        Dependency Trace
+-----------------+------------------------------------+
| Tier            | Files                              |
+-----------------+------------------------------------+
| T4 working_set  | src/auth/login.py                  |
| T3 reference    | src/auth/session.py, src/core/db.py|
| T2 signatures   | src/utils/crypto.py                |
+-----------------+------------------------------------+
```

### Apply to Scope

Add `--apply` to write the results to `.consurg.yaml`:

```bash
consurg trace src/auth/login.py --apply
```

If a scope file already exists, it's updated. If not, a new one is created.

### Multiple Entry Points

```bash
consurg trace src/auth/login.py src/auth/register.py --depth 3 --apply
```

All entry files get T4. Their combined dependency graphs are merged.

## Supported Languages

### Python

Uses `ast.walk()` for accurate import resolution:

- `import foo` -- resolves `foo.py` or `foo/__init__.py`
- `from foo import bar` -- resolves `foo.py` or `foo/bar.py`
- `from . import sibling` -- relative imports resolved against the file's package
- `from ..parent import module` -- multi-level relative imports

Handles:
- Package imports with `__init__.py`
- Relative imports (`.`, `..`, `...`)
- Multiple imports on one line

### TypeScript/JavaScript

Uses regex-based line parsing for:

- `import { x } from './module'`
- `import x from './module'`
- `export { x } from './module'`
- `const x = require('./module')`
- `const x = await import('./module')` (dynamic imports)
- `import type { T } from './types'` (marked as TYPE_ONLY dependencies)

Handles:
- Extension resolution (`.ts`, `.tsx`, `.js`, `.jsx`, `.mts`, `.mjs`)
- Index file resolution (`./dir` resolves to `./dir/index.ts`)
- `tsconfig.json` path aliases and `baseUrl` mapping
- Named re-exports

## Git Diff Command

```bash
consurg git-diff [base_branch] [--apply]
```

### How It Works

1. Runs `git diff --name-only <base>...HEAD` to find changed files
2. Traces one level of dependencies from changed files
3. Changed files get T4 (working_set)
4. Their direct dependencies get T3 (reference)

### Base Branch Detection

If no base branch is specified, Context Surgeon auto-detects:
1. Checks for `main`
2. Falls back to `master`
3. Errors if neither exists

### Example

```bash
# Auto-detect base branch
consurg git-diff --apply

# Explicit base
consurg git-diff develop --apply
```

Output:
```
   Git Diff Scope (base: main)
+-----------------+------------------------------------------+
| Tier            | Files                                    |
+-----------------+------------------------------------------+
| T4 working_set  | src/auth/login.py, tests/test_login.py   |
| T3 reference    | src/core/database.py                     |
+-----------------+------------------------------------------+
```

## Dependency Graph API

For programmatic use:

```python
from consurg.trace import DependencyGraph, resolve_python_imports

graph = DependencyGraph()

# Add edges manually or via resolvers
deps = resolve_python_imports("src/auth/login.py", project_root)
for dep_path, kind in deps:
    graph.add_edge("src/auth/login.py", dep_path, kind)

# Classify into tiers
tiers = graph.classify_tiers(["src/auth/login.py"])
# {"src/auth/login.py": 4, "src/core/db.py": 3, ...}
```

### Dependency Kinds

| Kind | Meaning |
|------|---------|
| `IMPORT` | Standard import dependency |
| `TYPE_ONLY` | TypeScript `import type` (does not affect runtime) |

## Signature Extraction

Context Surgeon can extract function and class signatures from files:

```python
from consurg.trace.signatures import extract_signatures

sigs = extract_signatures("src/auth/login.py")
# ["def authenticate(username: str, password: str) -> User:",
#  "class AuthManager:"]
```

Supports:
- **Python:** `def`, `async def`, `class` (with base classes)
- **TypeScript:** `function`, `class`, `interface`, `type`, arrow functions
