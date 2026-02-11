# Scope Schema Reference

## File: `.consurg.yaml`

The scope file is the core configuration. It lives in the project root and defines which files belong to which tier.

## Full Schema

```yaml
# Required: must be 1
version: 1

# Scope name (string, typically task-oriented)
scope: auth-refactor

# Whether enforcement is active (boolean)
active: true

# Optional human-readable description
reason: "Restricting agent to auth module for login bug fix"

# Tier 4: READ-WRITE (files the agent can modify)
working_set:
  - src/auth/*.py
  - tests/test_auth.py

# Tier 3: READ-ONLY (files the agent can read but not modify)
reference:
  - src/core/*.py
  - docs/auth.md

# Tier 2: SIGNATURE-ONLY (only function/class headers visible)
signatures:
  - types/*.pyi

# Tier 1: EXISTENCE-ONLY (filename visible, no content)
visible:
  - config.yaml

# Reserved: computed dependencies (list of patterns)
dynamic_deps: []

# Reserved: explorer mode bypass for reads (boolean)
explorer: false
```

## Field Reference

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `version` | int | Yes | - | Must be `1` |
| `scope` | string | Yes | - | Scope name (task-oriented identifier) |
| `active` | bool | Yes | `true` | Whether enforcement is active |
| `reason` | string | No | `""` | Human-readable reason for the scope |
| `working_set` | list[str] | No | `[]` | T4 patterns (read-write) |
| `reference` | list[str] | No | `[]` | T3 patterns (read-only) |
| `signatures` | list[str] | No | `[]` | T2 patterns (signatures only) |
| `visible` | list[str] | No | `[]` | T1 patterns (existence only) |
| `dynamic_deps` | list[str] | No | `[]` | Reserved for computed dependencies |
| `explorer` | bool | No | `false` | Bypass read restrictions (writes still enforced) |

## Pattern Format

Patterns use Python's `fnmatch` (shell-style wildcards):

| Wildcard | Matches |
|----------|---------|
| `*` | Any sequence of characters (except path separator) |
| `?` | Any single character |
| `[seq]` | Any character in `seq` |
| `[!seq]` | Any character NOT in `seq` |

**Note:** `fnmatch` does not support `**` recursive globbing. Each `*` matches within a single directory level.

**Windows paths:** Patterns always use forward slashes (`/`) as path separators, even on Windows. Context Surgeon normalizes backslashes internally before matching.

**Concurrent access:** `.consurg.yaml` has no file locking. Avoid concurrent modifications from multiple terminals. For multi-agent setups, use `narrow_scope()` to create separate child scope objects in memory.

### Pattern Examples

```yaml
working_set:
  - src/auth.py           # Exact file
  - src/auth/*.py         # All .py in src/auth/
  - tests/test_auth*.py   # test_auth.py, test_auth_login.py, etc.

reference:
  - "*.md"                # All markdown in root
  - src/core/*            # Everything in src/core/

signatures:
  - types/*.pyi           # Python stub files
  - src/interfaces/*.ts   # TypeScript interfaces

visible:
  - pyproject.toml        # Build config
  - .env.example          # Env template
```

## Resolution Order

Tiers are checked in descending order (T4 first). First match wins:

1. `working_set` patterns (T4)
2. `reference` patterns (T3)
3. `signatures` patterns (T2)
4. `visible` patterns (T1)
5. No match = T0 BLOCKED

If a file matches multiple tiers, the highest tier applies.

## Loading Programmatically

```python
from consurg.scope import load_scope, Scope
from pathlib import Path

# Load from file
scope = load_scope(Path(".consurg.yaml"))

# Create programmatically
scope = Scope(
    version=1,
    scope_name="my-scope",
    active=True,
    reason="Testing",
    working_set=["src/auth/*.py"],
    reference=["src/core/*.py"],
    signatures=[],
    visible=[],
)
```

## Scope Dataclass

```python
@dataclass
class Scope:
    version: int
    scope_name: str
    active: bool
    reason: str
    working_set: list[str]
    reference: list[str]
    signatures: list[str]
    visible: list[str]
    dynamic_deps: list[str]
    explorer: bool
```
