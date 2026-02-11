# Architecture Reference

## System Overview

```
+-------------------+     +-------------------+     +-------------------+
|   AI Agent        |     |   Context Surgeon |     |   User            |
|   (Claude, etc.)  |     |   Enforcement     |     |   (Terminal)      |
+--------+----------+     +--------+----------+     +--------+----------+
         |                         |                          |
         | tool call               |                          |
         v                         |                          |
+--------+----------+              |                          |
|   Hook Script     +--------------+                          |
|   (enforce_guard) |                                         |
+--------+----------+                                         |
         |                                                    |
         | POST /evaluate                                     |
         v                                                    |
+--------+----------+     +-------------------+     +---------+---------+
|   Guard Server    +-----+   Guard State     +-----+   Guard TUI      |
|   (HTTP thread)   |     |   (thread-safe)   |     |   (Rich Live)    |
+-------------------+     +--------+----------+     +-------------------+
                                   |
                          +--------+----------+
                          |   Keyboard Thread |
                          |   (msvcrt/tty)    |
                          +-------------------+
```

## Package Structure

> **Canonical source:** The actual package layout is defined by the source tree itself. See `cli-py` for CLI commands and `pyproject.toml` for the installed entry point.

```
consurg/
  __init__.py             Module docstring
  __main__.py             Entry point (calls app())
  cli.py                  Typer CLI (all commands)
  scope.py                Scope dataclass, YAML loading, narrowing, conflict detection
  enforce.py              resolve_tier() - fnmatch-based tier resolution (6 lines)

  guard/
    state.py              GuardState, AccessEvent, ApprovalRequest
    lockfile.py           .consurg-guard.lock management
    server.py             HTTPServer + /evaluate endpoint
    tui.py                Rich Live TUI + keyboard listener

  wire/
    __init__.py           WIRERS registry dict
    base.py               BaseWirer ABC
    claude.py             Claude Code (.claude/hooks.json)
    pk_agent.py           pk-agent (.pk-agent/hooks.json)
    droid.py              PuzlD AI (~/.puzldai/trusted-dirs.json)
    gemini.py             Gemini CLI (MCP wrapper + ~/.gemini/mcp_config.json)
    codex.py              Codex CLI (MCP wrapper + ~/.codex/mcp.json)

  adapters/
    claude.py             Markdown scope format
    cursor.py             Cursor rules format
    aider.py              Aider CLI args format
    generic.py            Plain text format

  trace/
    graph.py              DependencyGraph, BFS tier classification
    python_resolver.py    Python import resolution (ast-based)
    ts_resolver.py        TypeScript import resolution (regex-based)
    signatures.py         Function/class signature extraction

hooks/
  enforce.py              Direct enforcement hook
  enforce_guard.py        Guard-aware dual-path hook

tests/                    176 tests across 11 test files
```

## Data Flow: Without Guard

```
Agent calls Read("src/db.py")
  -> Claude Code invokes PreToolUse hook
    -> hooks/enforce.py reads stdin JSON
      -> loads .consurg.yaml
      -> resolve_tier("src/db.py", scope)
      -> tier=0, label="BLOCKED"
      -> exit 2 + stderr JSON
    <- Claude Code blocks the tool call
  <- Agent sees denial system message
```

## Data Flow: With Guard

```
Agent calls Read("src/db.py")
  -> hooks/enforce_guard.py reads stdin JSON
    -> reads .consurg-guard.lock -> port=9876
    -> POST http://127.0.0.1:9876/evaluate
      -> Guard resolves tier: T0 BLOCKED
      -> Interactive: creates ApprovalRequest
      -> TUI shows prompt, user presses 'r'
      -> Guard promotes src/db.py to T3
      -> Returns {"decision": "allow", "tier": 3}
    <- Hook receives allow -> exit 0
  <- Agent reads file successfully
```

## Data Flow: Fallback

```
Agent calls Read("src/db.py")
  -> hooks/enforce_guard.py
    -> reads lockfile -> port=9876
    -> POST -> connection refused
    -> Fallback: loads .consurg.yaml
    -> resolve_tier() -> tier=0 -> exit 2
```

## Core Function: resolve_tier()

> **Canonical source:** `consurg/enforce.py`. The code below is a snapshot for reference.

The heart of enforcement is 6 lines:

```python
def resolve_tier(file_path: str, scope: Scope) -> tuple[int, str]:
    for pattern in scope.working_set:
        if fnmatch(file_path, pattern): return (4, "READ-WRITE")
    for pattern in scope.reference:
        if fnmatch(file_path, pattern): return (3, "READ-ONLY")
    for pattern in scope.signatures:
        if fnmatch(file_path, pattern): return (2, "SIGNATURE")
    for pattern in scope.visible:
        if fnmatch(file_path, pattern): return (1, "EXISTENCE")
    return (0, "BLOCKED")
```

## Threading Model

> **Canonical source:** See `guard-reference.md` for full threading details, HTTP API, and approval flow.

| Thread | Library | Role | Daemon |
|--------|---------|------|--------|
| Main | Rich Live | TUI rendering at 4 FPS | No |
| HTTP | http.server | Handles /evaluate, /health, /log | Yes |
| Keyboard | msvcrt/tty | Captures W/R/S/D/Q keypresses | Yes |

All mutations to `GuardState` are protected by `threading.Lock`.

## Dependencies

| Dependency | Version | Purpose |
|------------|---------|---------|
| `typer` | >=0.9.0 | CLI framework |
| `rich` | >=13.0.0 | Terminal UI (tables, trees, panels, Live) |
| `pyyaml` | >=6.0 | YAML parsing |

Everything else is Python stdlib: `http.server`, `threading`, `fnmatch`, `ast`, `json`, `urllib.request`, `msvcrt`/`tty`/`select`.

## Testing

176 tests across 11 files:

```bash
python -m pytest tests/ -v                    # All tests
python -m pytest tests/test_guard.py -v       # Guard tests
python -m pytest tests/test_wire.py -v        # Wire tests
python -m pytest tests/test_trace.py -v       # Trace tests
```
