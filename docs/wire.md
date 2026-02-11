# Wire System

The wire system auto-configures hooks and integrations for supported AI tools. One command to connect, one to disconnect.

## Usage

```bash
# Install hooks
consurg wire <tool>

# Remove hooks
consurg wire <tool> --unwire

# Check status after wiring
consurg wire <tool>
```

## Supported Tools

### Claude Code

```bash
consurg wire claude
```

**What it does:** Creates `.claude/hooks.json` in your project with a `PreToolUse` hook pointing to `hooks/enforce_guard.py`.

**Generated config:**
```json
{
  "hooks": {
    "PreToolUse": [
      {
        "type": "command",
        "command": "python /path/to/hooks/enforce_guard.py"
      }
    ]
  }
}
```

**How it works:** Claude Code runs the hook before every tool call (`Read`, `Edit`, `Write`, `Grep`, `Glob`). The hook reads stdin JSON, evaluates the file against the scope, and exits with code 0 (allow) or 2 (deny with a system message).

**Preserves existing hooks:** If `.claude/hooks.json` already has other PreToolUse hooks, the consurg hook is appended without removing them.

### pk-agent

```bash
consurg wire pk-agent
```

**What it does:** Creates `.pk-agent/hooks.json` with a `tool:start` event hook.

**Generated config:**
```json
{
  "hooks": {
    "tool:start": [
      {
        "type": "command",
        "command": "python /path/to/hooks/enforce_guard.py"
      }
    ]
  }
}
```

### PuzlD AI (droid)

```bash
consurg wire droid
```

**What it does:** Adds a consurg-marked entry to `~/.puzldai/trusted-dirs.json`.

**Generated config:**
```json
{
  "trusted_dirs": [
    {
      "path": "/path/to/project",
      "scope": "consurg",
      "marker": "consurg:/path/to/project"
    }
  ]
}
```

The marker ensures idempotent wiring and clean unwiring.

### Gemini CLI

```bash
consurg wire gemini
```

**What it does:** Generates two things:
1. An MCP server wrapper script at `hooks/consurg_mcp_gemini.py`
2. An entry in `~/.gemini/mcp_config.json`

**Why MCP?** Gemini CLI lacks native hook APIs. The MCP wrapper acts as a proxy that intercepts tool calls and enforces scope access before passing them through.

**Generated MCP config:**
```json
{
  "mcpServers": {
    "consurg": {
      "command": "python",
      "args": ["/path/to/hooks/consurg_mcp_gemini.py"]
    }
  }
}
```

The wrapper script connects to the guard server if running, otherwise falls back to direct scope enforcement.

### Codex CLI

```bash
consurg wire codex
```

**What it does:** Same pattern as Gemini -- generates an MCP wrapper at `hooks/consurg_mcp_codex.py` and adds it to `~/.codex/mcp.json`.

## Idempotency

All wirers are idempotent. Running `consurg wire claude` twice does not create duplicate hooks. The second invocation detects the existing hook and reports "Already wired."

## Unwiring

```bash
consurg wire claude --unwire
```

Removes only the consurg hook/entry. Other hooks and configuration are preserved.

For Gemini and Codex, unwiring also removes the generated MCP wrapper script.

## Status Detection

After wiring or unwiring, the current status is displayed:

```
Wired to Claude Code (PreToolUse hook)
Config: /path/to/project/.claude/hooks.json
Status: wired
```

Possible statuses:
- `wired` -- hooks are installed and functional
- `not wired` -- no consurg hooks found
- `partial` -- config exists but wrapper script is missing (Gemini/Codex only)

## Guard Integration

The hook scripts (`enforce_guard.py` and MCP wrappers) follow a dual-path strategy:

1. Check for `.consurg-guard.lock` in the project root
2. If found and the guard is reachable, send `POST /evaluate` to the guard
3. If the guard is unreachable, fall back to direct scope enforcement

This means:
- **Guard running:** Interactive approval, real-time access log, live tier promotion
- **Guard not running:** Silent enforcement based on `.consurg.yaml` (same tier logic, no interactivity)
