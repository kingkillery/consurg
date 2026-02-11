# Export Adapters Reference

Context Surgeon exports scopes in tool-specific formats for manual integration or when the wire system does not cover a tool.

## Usage

```bash
consurg export --format <format>
```

Output is printed to stdout. Pipe or redirect as needed:

```bash
consurg export --format claude > scope.md
consurg export --format aider | xargs aider
```

## Formats

### Claude (`--format claude`)

Generates Markdown for system prompt injection:

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

### Cursor (`--format cursor`)

Generates Cursor rules format with prefixed patterns:

```
# Context Surgeon Scope: auth-refactor
#
# File access restrictions are in effect.
# Only interact with files listed below at their designated tier.

# READ-WRITE (full access)
allow: src/auth/*.py
allow: tests/test_auth.py

# READ-ONLY
read-only: src/core/*.py
read-only: docs/auth.md

# SIGNATURE-ONLY
signature: types/*.pyi

# EXISTENCE-ONLY
visible: config.yaml

# All other files are BLOCKED.
```

### Aider (`--format aider`)

Generates CLI arguments for aider:

```
--file src/auth/*.py --file tests/test_auth.py --read src/core/*.py --read docs/auth.md
```

### Generic (`--format generic`)

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

## Programmatic API

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

markdown = generate_claude_scope(scope)      # Returns str
rules = generate_cursor_rules(scope)         # Returns str
args = generate_aider_args(scope)            # Returns list[str]
text = generate_generic_prompt(scope)        # Returns str
```

## When to Use Export vs Wire

| Scenario | Approach |
|----------|----------|
| Tool supports hooks (Claude Code, pk-agent) | `consurg wire` |
| Tool uses MCP (Gemini, Codex) | `consurg wire` |
| Tool reads system prompt from file | `consurg export` + paste output |
| Tool accepts CLI flags | `consurg export --format aider` |
| Custom or unsupported tool | `consurg export --format generic` |

Export is passive (generates text to paste or pipe). Wire is active (installs enforcement that runs automatically).
