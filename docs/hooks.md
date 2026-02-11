# Hook System

Context Surgeon enforces scope through hook scripts that intercept AI tool calls before they execute.

## Hook Scripts

There are two hook scripts in the `hooks/` directory:

### `hooks/enforce.py` -- Direct enforcement

The original hook. Reads the scope from `.consurg.yaml`, resolves the file's tier, and allows or denies directly. No guard server needed.

```
stdin (JSON) -> resolve_tier() -> exit 0 (allow) or exit 2 (deny)
```

### `hooks/enforce_guard.py` -- Guard-aware enforcement

The enhanced hook. Tries the guard server first for interactive approval, then falls back to direct enforcement.

```
stdin (JSON) -> check lockfile -> POST /evaluate (if guard running)
                               -> resolve_tier() (if guard not running)
            -> exit 0 (allow) or exit 2 (deny)
```

**When to use which:**
- Use `enforce.py` if you want simple, silent enforcement with no guard dependency
- Use `enforce_guard.py` if you want interactive approval when the guard is running, with automatic fallback when it's not

The `consurg wire` command always configures `enforce_guard.py`.

## Hook Protocol

Hooks follow the Claude Code PreToolUse hook contract:

### Input (stdin)

The hook receives a JSON object on stdin:

```json
{
  "tool_name": "Read",
  "tool_input": {
    "file_path": "/absolute/path/to/src/auth.py"
  },
  "cwd": "/path/to/project"
}
```

### Tool Name Mapping

The hook extracts the file path from `tool_input` using this mapping:

| Tool | Input Field |
|------|-------------|
| `Read` | `file_path` |
| `Edit` | `file_path` |
| `Write` | `file_path` |
| `Grep` | `path` |
| `Glob` | `path` |

Unknown tools (e.g., `Bash`, `WebSearch`) are always allowed (exit 0).

### Path Normalization

Absolute paths are converted to relative paths (relative to `cwd`) before matching against scope patterns. This ensures patterns like `src/auth.py` match regardless of the project's absolute location.

### Output

**Allow:** Exit code `0`, no output.

**Deny:** Exit code `2`, with a JSON payload on stderr:

```json
{
  "hookSpecificOutput": {
    "permissionDecision": "deny"
  },
  "systemMessage": "[CONTEXT SURGEON: ACCESS DENIED]\nFile: src/db.py\nTier: BLOCKED (Tier 0)\nScope: auth-refactor\nReason: Not in working set or dependency graph.\nAction: State which file you need and why. User will decide."
}
```

The `systemMessage` is injected into the agent's context, informing it why access was denied and what it should do next.

### Deny Scenarios

| Scenario | Message |
|----------|---------|
| T0/T1 file, any tool | ACCESS DENIED -- file not in scope |
| T2/T3 file, `Edit`/`Write` | WRITE BLOCKED -- file is read-only |

### Explorer Mode

When `explorer: true` is set in the scope, read tools (`Read`, `Grep`, `Glob`) bypass tier checks. Write tools still follow normal tier restrictions.

## Violation Logging

Set `CONSURG_LOG=1` to enable violation logging. Denied accesses are appended to `.consurg-violations.log`:

```
[2024-01-15T10:30:00+00:00] DENIED tool=Read file=src/db.py tier=BLOCKED scope=auth-refactor
```

Only `hooks/enforce.py` writes to this log. `hooks/enforce_guard.py` relies on the guard's access log instead.

## Writing Custom Hooks

To integrate Context Surgeon with a tool not covered by the wire system, write a hook script that:

1. Reads JSON from stdin (tool name + file path)
2. Calls `resolve_tier(file_path, scope)` from `consurg.enforce`
3. Exits with code 0 (allow) or 2 (deny)

Example minimal hook:

```python
#!/usr/bin/env python3
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from consurg.enforce import resolve_tier
from consurg.scope import load_scope

data = json.load(sys.stdin)
scope = load_scope(Path(data["cwd"]) / ".consurg.yaml")

if scope is None or not scope.active:
    sys.exit(0)

tier, label = resolve_tier(data["file_path"], scope)
if tier <= 1:
    sys.exit(2)
sys.exit(0)
```
