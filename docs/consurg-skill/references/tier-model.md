# Tier Model Reference

## Tier Definitions

### Tier 4: READ-WRITE (`working_set`)

Full access. The agent can read, edit, and write these files.

```yaml
working_set:
  - src/auth/*.py
  - tests/test_auth.py
```

**When to assign:** Files the agent is actively modifying for the current task.

### Tier 3: READ-ONLY (`reference`)

Read access only. Attempts to `Edit` or `Write` are blocked with a structured denial.

```yaml
reference:
  - src/core/database.py
  - docs/api.md
```

**When to assign:** Dependencies, documentation, configuration that provides context without allowing modification.

### Tier 2: SIGNATURE-ONLY (`signatures`)

Function signatures, class definitions, and interface declarations only. Implementation bodies are not accessible. Equivalent to `.d.ts` or `.pyi` stubs.

```yaml
signatures:
  - types/*.pyi
  - src/interfaces/*.ts
```

**When to assign:** Type stubs, interface files, or modules where only the API surface matters.

### Tier 1: EXISTENCE-ONLY (`visible`)

Filename appears in directory listings. No content access of any kind.

```yaml
visible:
  - config.yaml
  - .env.example
```

**When to assign:** Files the agent should be aware of (to avoid creating duplicates) but has no reason to read.

### Tier 0: BLOCKED _(implicit)_

File is invisible. All operations blocked: Read, Write, Edit, Grep, Glob. This is the default for any file not matching a pattern in tiers 1-4.

## Tool-Tier Matrix

| Tool | T4 | T3 | T2 | T1 | T0 |
|------|----|----|----|----|-----|
| `Read` | Allow | Allow | Allow | Deny | Deny |
| `Grep` | Allow | Allow | Allow | Deny | Deny |
| `Glob` | Allow | Allow | Allow | Deny | Deny |
| `Edit` | Allow | Deny | Deny | Deny | Deny |
| `Write` | Allow | Deny | Deny | Deny | Deny |

Write operations (`Edit`, `Write`) require T4. Read operations (`Read`, `Grep`, `Glob`) require T2 or higher.

## Pattern Matching

Patterns use Python's `fnmatch` (shell-style wildcards):

| Pattern | Matches |
|---------|---------|
| `src/auth.py` | Exactly `src/auth.py` |
| `src/*.py` | Any `.py` file directly in `src/` |
| `*.py` | Any `.py` file in the root directory |
| `tests/test_*.py` | `tests/test_auth.py`, `tests/test_db.py`, etc. |
| `src/auth/*` | Any file directly in `src/auth/` |

**Important:** `fnmatch` does not support recursive `**` globbing. Use `src/auth/*` for single-level matching.

## Tier Precedence

Tiers are evaluated in descending order. First matching pattern wins:

1. Check `working_set` (T4)
2. Check `reference` (T3)
3. Check `signatures` (T2)
4. Check `visible` (T1)
5. Default to BLOCKED (T0)

If a file matches patterns in multiple tiers, the highest tier applies.

## Explorer Mode

Setting `explorer: true` in the scope allows all read operations on all files regardless of tier. Write operations still follow normal tier restrictions.

```yaml
explorer: true
```

Useful during initial investigation when broad read access is needed but write access must remain restricted.

## Drift Detection

Context Surgeon tracks scope expansion. When total patterns exceed 2x the original count, a drift warning is displayed:

```
Drift Warning
Original file count: 5
Current file count: 12
Expansion ratio: 2.4x
```

This prevents gradual scope erosion where a tight scope creeps until it covers most of the project.

## Scope Narrowing

Child scopes inherit the parent scope as a ceiling. Files in the child scope retain their parent tier and cannot be promoted:

```python
from consurg.scope import narrow_scope

child = narrow_scope(parent_scope, ["src/auth/login.py", "src/core/db.py"])
# src/auth/login.py inherits parent tier (e.g., T4)
# src/core/db.py inherits parent tier (e.g., T3)
```

Attempting to include a T0 file from the parent raises `ScopeError`. This enforces monotonic narrowing for multi-agent setups.

## Write Conflict Detection

Detect overlapping T4 (working_set) patterns across multiple scopes:

```python
from consurg.scope import detect_write_conflicts

conflicts = detect_write_conflicts([scope_a, scope_b])
# Returns patterns that overlap in working_set
```

Critical for multi-agent coordination where two agents should never have write access to the same file.
