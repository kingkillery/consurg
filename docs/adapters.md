# Export Adapters

Context Surgeon can export scopes in tool-specific formats for manual integration or when the wire system doesn't cover your tool.

## Usage

```bash
consurg export --format <format>
```

Available formats: `claude`, `cursor`, `aider`, `generic`

## Formats

### Claude

```bash
consurg export --format claude
```

Generates a Markdown document suitable for injection into Claude's system prompt:

```markdown
# Context Surgeon Scope: auth-refactor

## Working Set (READ-WRITE)
- src/auth/*.py
- tests/test_auth.py

## Reference (READ-ONLY)
- src/core/*.py
- docs/auth.md

## Signatures (SIGNATURE-ONLY)
- types/*.pyi

All other files are **BLOCKED**. Do not read, write, grep, or glob outside the listed tiers.
If you need access to a file not listed, ask the user.
```

### Cursor

```bash
consurg export --format cursor
```

Generates Cursor rules format:

```
# Context Surgeon Scope: auth-refactor
#
# READ-WRITE (full access)
allow: src/auth/*.py
allow: tests/test_auth.py
#
# READ-ONLY
read-only: src/core/*.py
read-only: docs/auth.md
#
# SIGNATURE-ONLY
sig-only: types/*.pyi
#
# All other files are BLOCKED.
```

### Aider

```bash
consurg export --format aider
```

Generates command-line arguments for aider:

```
--file src/auth/*.py --file tests/test_auth.py --read src/core/*.py --read docs/auth.md
```

### Generic

```bash
consurg export --format generic
```

Generates a plain-text scope summary:

```
[SCOPE: auth-refactor]
Tier 4 - READ-WRITE:
  src/auth/*.py
  tests/test_auth.py
Tier 3 - READ-ONLY:
  src/core/*.py
  docs/auth.md
Tier 2 - SIGNATURE-ONLY:
  types/*.pyi
Tier 1 - EXISTENCE-ONLY:
  (none)

All files not listed above are BLOCKED (Tier 0).
```

## Programmatic Use

```python
from consurg.adapters import (
    generate_claude_scope,
    generate_cursor_rules,
    generate_aider_args,
    generate_generic_prompt,
)
from consurg.scope import load_scope
from pathlib import Path

scope = load_scope(Path(".consurg.yaml"))

# Each returns a string (or list for aider)
markdown = generate_claude_scope(scope)
rules = generate_cursor_rules(scope)
args = generate_aider_args(scope)     # Returns list[str]
text = generate_generic_prompt(scope)
```

## When to Use Export vs Wire

| Scenario | Use |
|----------|-----|
| Tool supports hooks (Claude Code, pk-agent) | `consurg wire` |
| Tool uses MCP (Gemini, Codex) | `consurg wire` |
| Tool reads system prompt from file | `consurg export` + paste output |
| Tool accepts CLI flags | `consurg export --format aider` |
| Custom integration | `consurg export --format generic` |

Export is passive -- it generates text you paste or pipe. Wire is active -- it installs enforcement that runs automatically.
