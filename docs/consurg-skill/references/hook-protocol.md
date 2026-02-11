# Hook Protocol Reference

Context Surgeon enforces scope through hook scripts that intercept AI tool calls before execution.

## Hook Scripts

### `hooks/enforce.py` -- Direct Enforcement

Reads `.consurg.yaml`, resolves tier, allows or denies. No guard dependency.

```
stdin (JSON) -> resolve_tier() -> exit 0 (allow) or exit 2 (deny)
```

### `hooks/enforce_guard.py` -- Guard-Aware Enforcement

Tries guard server first, falls back to direct enforcement:

```
stdin (JSON) -> check lockfile -> POST /evaluate (guard running)
                               -> resolve_tier() (guard not running)
            -> exit 0 (allow) or exit 2 (deny)
```

`consurg wire` always configures `enforce_guard.py`.

## Input Format (stdin)

```json
{
  "tool_name": "Read",
  "tool_input": {
    "file_path": "/absolute/path/to/src/auth.py"
  },
  "cwd": "/path/to/project"
}
```

## Tool Name to Path Mapping

| Tool | Input Field |
|------|-------------|
| `Read` | `tool_input.file_path` |
| `Edit` | `tool_input.file_path` |
| `Write` | `tool_input.file_path` |
| `Grep` | `tool_input.path` |
| `Glob` | `tool_input.path` |

Unknown tools (e.g., `Bash`, `WebSearch`) are always allowed (exit 0).

## Path Normalization

Absolute paths are converted to relative paths (relative to `cwd`) before matching against scope patterns. This ensures patterns like `src/auth.py` match regardless of absolute project location.

## Output Format

**Allow:** Exit code `0`, no output.

**Deny:** Exit code `2`, with JSON on stderr:

```json
{
  "hookSpecificOutput": {
    "permissionDecision": "deny"
  },
  "systemMessage": "[CONTEXT SURGEON: ACCESS DENIED]\nFile: src/db.py\nTier: BLOCKED (Tier 0)\nScope: auth-refactor\nReason: Not in working set or dependency graph.\nAction: State which file you need and why. User will decide."
}
```

The `systemMessage` is injected into the agent's context as feedback.

## Denial Scenarios

| Scenario | Message |
|----------|---------|
| T0/T1 file, any tool | ACCESS DENIED -- file not in scope |
| T2/T3 file, `Edit`/`Write` | WRITE BLOCKED -- file is read-only |

## Explorer Mode

When `explorer: true` in scope, read tools (`Read`, `Grep`, `Glob`) bypass tier checks. Write tools follow normal restrictions.

## Violation Logging

Set `CONSURG_LOG=1` to enable violation logging. Denied accesses append to `.consurg-violations.log`:

```
[2024-01-15T10:30:00+00:00] DENIED tool=Read file=src/db.py tier=BLOCKED scope=auth-refactor
```

Only `hooks/enforce.py` writes to this log. `hooks/enforce_guard.py` relies on the guard's access log.

## Writing Custom Hooks

To integrate with an unsupported tool, write a hook that:

1. Reads JSON from stdin (tool name + file path)
2. Calls `resolve_tier(file_path, scope)` from `consurg.enforce`
3. Exits with code 0 (allow) or 2 (deny)

Minimal custom hook:

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

file_path = data.get("tool_input", {}).get("file_path", "")
if file_path:
    rel = str(Path(file_path).relative_to(data["cwd"]))
    tier, label = resolve_tier(rel, scope)
    if tier <= 1:
        sys.exit(2)

sys.exit(0)
```

Customize the tier threshold and denial message as needed for the target tool's hook protocol.

## Promoting Files Without the Guard

Without the interactive guard, the promotion workflow is manual:

1. Agent encounters a denial for a file
2. Edit `.consurg.yaml` to add the file to the appropriate tier list
3. The hook re-reads the scope file on every tool call, so changes take effect immediately
4. Agent retries the operation

With the guard running, this is handled interactively via the approval keys (W/R/S/D).
