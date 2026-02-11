# Architecture

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

```
consurg/
  __init__.py             Module docstring
  __main__.py             Entry point (calls app())
  cli.py                  Typer CLI (all commands)
  scope.py                Scope dataclass, YAML loading, narrowing, conflict detection
  enforce.py              resolve_tier() - fnmatch-based tier resolution

  guard/
    __init__.py           Guard exports
    state.py              GuardState, AccessEvent, ApprovalRequest
    lockfile.py           .consurg-guard.lock management
    server.py             HTTPServer + /evaluate endpoint
    tui.py                Rich Live TUI + keyboard listener

  wire/
    __init__.py           Wirer registry (WIRERS dict)
    base.py               BaseWirer ABC
    claude.py             Claude Code wirer (.claude/hooks.json)
    pk_agent.py           pk-agent wirer (.pk-agent/hooks.json)
    droid.py              PuzlD AI wirer (~/.puzldai/trusted-dirs.json)
    gemini.py             Gemini CLI wirer (MCP wrapper + ~/.gemini/mcp_config.json)
    codex.py              Codex CLI wirer (MCP wrapper + ~/.codex/mcp.json)

  adapters/
    __init__.py           Adapter exports
    claude.py             Markdown scope format
    cursor.py             Cursor rules format
    aider.py              Aider CLI args format
    generic.py            Plain text format

  trace/
    __init__.py           Trace exports
    graph.py              DependencyGraph, BFS tier classification
    python_resolver.py    Python import resolution (ast-based)
    ts_resolver.py        TypeScript import resolution (regex-based)
    signatures.py         Function/class signature extraction

hooks/
  enforce.py              Direct enforcement hook (no guard dependency)
  enforce_guard.py        Guard-aware hook (dual-path: guard -> fallback)

tests/
  test_cli.py             CLI commands (init, add, remove, on, off, status, map)
  test_cli_phase3.py      Trace and git-diff commands
  test_enforce.py         Tier resolution
  test_hook.py            Hook enforcement (allow/deny)
  test_scope.py           Scope loading and validation
  test_trace.py           Import resolution and graph classification
  test_adapters.py        Export adapters, narrowing, conflicts, explorer mode
  test_integration.py     End-to-end CLI + enforcement
  test_guard.py           Guard server, state, lockfile, approval
  test_wire.py            All wirers (wire, unwire, idempotency, status)
  test_wrap.py            Wrap command (env vars, lockfile, exit codes)
```

## Data Flow

### Enforcement Path (without guard)

```
Agent calls Read("src/db.py")
  -> Claude Code invokes PreToolUse hook
    -> hooks/enforce.py reads stdin JSON
      -> loads .consurg.yaml
      -> resolve_tier("src/db.py", scope)
      -> tier=0, label="BLOCKED"
      -> exit 2 + stderr JSON with deny message
    <- Claude Code blocks the tool call
  <- Agent sees system message explaining the denial
```

### Enforcement Path (with guard)

```
Agent calls Read("src/db.py")
  -> Claude Code invokes PreToolUse hook
    -> hooks/enforce_guard.py reads stdin JSON
      -> reads .consurg-guard.lock -> port=9876
      -> POST http://127.0.0.1:9876/evaluate
        -> Guard resolves tier: T0 BLOCKED
        -> Interactive mode: creates ApprovalRequest
        -> TUI shows approval prompt
        -> User presses 'r' (read-only)
        -> Guard promotes src/db.py to T3 in live scope
        -> Returns {"decision": "allow", "tier": 3}
      <- Hook receives allow
      -> exit 0
    <- Claude Code allows the tool call
  <- Agent reads src/db.py successfully
```

### Fallback Path

```
Agent calls Read("src/db.py")
  -> hooks/enforce_guard.py reads stdin JSON
    -> reads .consurg-guard.lock -> port=9876
    -> POST http://127.0.0.1:9876/evaluate -> connection refused
    -> Fallback: loads .consurg.yaml directly
    -> resolve_tier("src/db.py", scope)
    -> tier=0 -> exit 2 (deny)
```

## Threading Model

The guard uses three threads:

### HTTP Server Thread (daemon)

- `http.server.HTTPServer` from stdlib
- Handles `/evaluate`, `/health`, `/log` endpoints
- `/evaluate` may block up to 8 seconds when waiting for interactive approval
- All access to `GuardState` is protected by `threading.Lock`

### TUI Thread (main)

- Rich `Live` with `Layout` rendering at 4 FPS
- Reads from `GuardState` (access log, pending approvals, tier counts)
- Runs on the main thread so Rich can manage terminal state

### Keyboard Thread (daemon)

- Platform-specific input:
  - **Windows:** `msvcrt.getwch()` with 50ms polling
  - **Unix:** `tty.setraw()` + `select()` with 50ms timeout
- Sets `ApprovalRequest.response` and signals `ApprovalRequest.event`
- Also handles `Q` to quit

### Thread Safety

`GuardState` uses a `threading.Lock` for all mutations:
- `add_event()` -- appends to the access log deque
- `set_pending()` / `clear_pending()` -- manages the approval request
- `promote_file()` -- modifies the live scope's tier lists
- `tier_counts()` -- reads tier list lengths

The `ApprovalRequest.event` is a `threading.Event` used to signal the HTTP server thread when the keyboard thread processes user input.

## Lockfile Protocol

The lockfile (`.consurg-guard.lock`) is the rendezvous point between the guard and hook scripts:

1. Guard starts, writes lockfile with `{pid, port, scope}`
2. Hook script reads lockfile, extracts port
3. Hook checks PID liveness (cross-platform: `ctypes.OpenProcess` on Windows, `os.kill(pid, 0)` on Unix)
4. If PID is alive, hook POSTs to `127.0.0.1:<port>/evaluate`
5. If PID is dead or lockfile is missing, hook falls back to direct enforcement
6. Guard stops, removes lockfile

This design avoids environment variable propagation issues (some tools don't forward env vars to subprocesses).

## Wire Architecture

### Hook-based tools (Claude Code, pk-agent)

```
consurg wire claude
  -> writes .claude/hooks.json
    -> PreToolUse: ["python hooks/enforce_guard.py"]
  -> done

Claude Code starts
  -> loads hooks.json
  -> before each tool call: runs enforce_guard.py
  -> hook evaluates access
```

### Config-based tools (droid)

```
consurg wire droid
  -> writes ~/.puzldai/trusted-dirs.json
    -> adds project dir with consurg marker
  -> done
```

### MCP-based tools (Gemini, Codex)

```
consurg wire gemini
  -> generates hooks/consurg_mcp_gemini.py (MCP server wrapper)
  -> writes ~/.gemini/mcp_config.json
    -> mcpServers.consurg: python hooks/consurg_mcp_gemini.py
  -> done

Gemini CLI starts
  -> launches MCP server (consurg_mcp_gemini.py)
  -> MCP server intercepts tools/call
  -> checks scope via guard or direct enforcement
  -> blocks or passes through
```

## Dependencies

Runtime:
- `typer>=0.9.0` -- CLI framework
- `rich>=13.0.0` -- Terminal UI (tables, trees, panels, live display)
- `pyyaml>=6.0` -- YAML parsing

All other functionality uses Python stdlib:
- `http.server` -- guard HTTP server
- `threading` -- multi-threaded guard
- `msvcrt` (Windows) / `tty` + `select` (Unix) -- keyboard input
- `fnmatch` -- pattern matching
- `ast` -- Python import resolution
- `json` -- hook protocol and lockfile
- `urllib.request` -- hook-to-guard communication

Dev:
- `pytest>=7.0` -- testing
