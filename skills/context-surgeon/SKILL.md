---
name: context-surgeon
description: Use this skill when configuring, updating, or operating Consurg for agent context control (scopes, permission tiers, wire integrations, tracing, and enforcement) in CLI workflows.
---

# Context Surgeon (Consurg CLI)

Use this skill for any request to set up or adjust Consurg as a context-control tool for AI coding assistants.

## Scope model
- `working_set` (Tier 4): read/write files.
- `reference` (Tier 3): read-only files.
- `signatures` (Tier 2): API/type signatures.
- `visible` (Tier 1): file existence only.
- Unlisted items default to blocked.

## Common patterns

### Create and enforce a scope
```bash
consurg init <scope-name>
consurg add src/path.py tests/test_path.py
consurg add --read pyproject.toml docs/notes.md
consurg add --sig src/types.py
consurg on
consurg status
```

### Build scope from dependencies
```bash
consurg trace <entry-file> --depth <N>
consurg on
```

### Build scope from diffs
```bash
consurg git-diff [ref]
consurg on
```

### Remove scope and deactivate
```bash
consurg off
consurg remove src/path.py
consurg clean
```

## Tool wiring

Connect Consurg enforcement to an assistant tool:
- `consurg wire claude`
- `consurg wire codex`
- `consurg wire gemini`
- `consurg wire pk-agent`
- `consurg wire droid`

Use `--unwire` to remove generated hook or integration files.

## Enforcement and operations
- `consurg guard` starts interactive runtime guard.
- `consurg wrap -- <command>` runs a command inside Consurg enforcement.
- `consurg pin` / `consurg wire <tool> --unwire` handle durable scope/session state.
- `consurg export --format <claude|cursor|aider|generic>` exports a scope.
- `consurg map` and `consurg status` inspect active state.

## Practical rules
- Use minimal scope first, then expand only when blocked access blocks legitimate work.
- Prefer iterative tightening: start with `working_set`, then add `reference`/`signatures` as needed.
- For broad investigation, promote `explorer: true` only when needed, then remove it before final edits.
