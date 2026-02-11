# Tier Model

Context Surgeon uses a 5-tier access control model. Every file in your project falls into exactly one tier based on pattern matching against the scope definition.

## Tier Definitions

### Tier 4: READ-WRITE (`working_set`)

Full access. The agent can read, edit, and write these files. This is where the agent does its actual work.

```yaml
working_set:
  - src/auth/*.py
  - tests/test_auth.py
```

**When to use:** Files the agent is actively modifying for the current task.

### Tier 3: READ-ONLY (`reference`)

The agent can read these files for context but cannot modify them. Attempts to use `Edit` or `Write` tools on T3 files are blocked.

```yaml
reference:
  - src/core/database.py
  - docs/api.md
```

**When to use:** Dependencies, documentation, configuration files the agent needs to understand but should not change.

### Tier 2: SIGNATURE-ONLY (`signatures`)

The agent can view function signatures, class definitions, and interface declarations. Full file content is not accessible, but the agent can understand the API surface.

```yaml
signatures:
  - types/*.pyi
  - src/interfaces/*.ts
```

**When to use:** Type stubs, interface files, or modules where the agent only needs to know the API shape.

### Tier 1: EXISTENCE-ONLY (`visible`)

The agent knows these files exist and can reference them by name, but cannot read their content.

```yaml
visible:
  - config.yaml
  - .env.example
```

**When to use:** Files the agent should be aware of (to avoid creating duplicates) but has no reason to read.

### Tier 0: BLOCKED _(implicit)_

Any file not matching a pattern in tiers 1-4. The agent cannot access these files at all. Read, write, grep, and glob operations are all blocked.

**This is the default.** Files must be explicitly added to a tier to be accessible.

## Pattern Matching

Patterns use Python's `fnmatch` (shell-style wildcards):

| Pattern | Matches |
|---------|---------|
| `src/auth.py` | Exactly `src/auth.py` |
| `src/*.py` | Any `.py` file directly in `src/` |
| `*.py` | Any `.py` file in the root |
| `tests/test_*.py` | Files like `tests/test_auth.py`, `tests/test_db.py` |
| `src/auth/*` | Any file directly in `src/auth/` |

**Note:** `fnmatch` does not support recursive `**` globbing. Use `src/auth/*` for single-level matching.

## Tier Precedence

Tiers are evaluated in descending order (T4 first). The **first matching pattern wins**:

1. Check `working_set` (T4) patterns
2. Check `reference` (T3) patterns
3. Check `signatures` (T2) patterns
4. Check `visible` (T1) patterns
5. Default to BLOCKED (T0)

If a file matches patterns in multiple tiers, the highest tier applies. For example, if `src/auth.py` matches both a `working_set` pattern and a `reference` pattern, it gets T4 (READ-WRITE).

## Tool-Tier Matrix

| Tool | T4 | T3 | T2 | T1 | T0 |
|------|----|----|----|----|-----|
| `Read` | Allow | Allow | Allow | Deny | Deny |
| `Grep` | Allow | Allow | Allow | Deny | Deny |
| `Glob` | Allow | Allow | Allow | Deny | Deny |
| `Edit` | Allow | Deny | Deny | Deny | Deny |
| `Write` | Allow | Deny | Deny | Deny | Deny |

## Explorer Mode

When `explorer: true` is set in the scope, all read operations (`Read`, `Grep`, `Glob`) are allowed on **all files** regardless of tier. Write operations still follow tier restrictions.

```yaml
explorer: true
```

This is useful during initial investigation when you want the agent to explore the codebase freely but still prevent unauthorized writes.

## Drift Detection

When you add patterns, Context Surgeon tracks the original file count. If the total number of patterns across all tiers exceeds 2x the original count, a drift warning is displayed:

```
Drift Warning
Scope drift detected!
Original file count: 5
Current file count: 12
Expansion ratio: 2.4x
```

This helps catch scope creep where a tightly-defined scope gradually expands to cover most of the project.

## Scope Narrowing

Child scopes can be created from a parent scope. A child scope can only include files that are already in the parent scope, and files inherit their parent's tier (they cannot be promoted):

```python
from consurg.scope import narrow_scope

child = narrow_scope(parent_scope, ["src/auth/login.py", "src/core/db.py"])
# src/auth/login.py gets its parent tier (e.g., T4)
# src/core/db.py gets its parent tier (e.g., T3)
```

Attempting to include a file that's T0 in the parent raises `ScopeError`.

## Write Conflict Detection

When running multiple agents with overlapping scopes, Context Surgeon can detect write conflicts:

```python
from consurg.scope import detect_write_conflicts

conflicts = detect_write_conflicts([scope_a, scope_b])
# Returns patterns that overlap in working_set across scopes
```
