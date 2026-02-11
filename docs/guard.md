# Interactive Guard

The guard is a real-time scope firewall that intercepts every file access from your AI agent. It runs as a local HTTP server with an optional TUI dashboard.

## Starting the Guard

### Interactive TUI mode (default)

```bash
consurg guard -i
```

This opens a full-screen terminal dashboard with three panels:

1. **Header** -- Scope name, active status, tier counts, port, uptime
2. **Access log** -- Scrolling table of recent file access events
3. **Approval prompt** -- Appears when a blocked access needs your decision

### Headless mode

```bash
consurg guard --no-tui
```

Runs the HTTP server without the TUI. Useful for CI, scripts, or when you want enforcement without the visual dashboard. Press `Ctrl+C` to stop.

### Custom port

```bash
consurg guard -i --port 8888
```

Default port is `9876`.

## How It Works

### Architecture

```
                    +------------------+
                    |   Guard Server   |
                    |  (HTTP thread)   |
                    +--------+---------+
                             |
              +--------------+--------------+
              |              |              |
     +--------v---+  +-------v------+  +----v-------+
     |   TUI      |  |   Keyboard   |  |  Lockfile  |
     | (Rich Live)|  |   listener   |  | .consurg-  |
     |   thread   |  |   thread     |  | guard.lock |
     +------------+  +--------------+  +------------+
```

Three threads, zero new dependencies:
- **HTTP server thread** (`http.server`, stdlib) -- receives hook requests on `POST /evaluate`
- **TUI thread** (Rich Live) -- renders the dashboard at 4 FPS
- **Keyboard thread** (`msvcrt` on Windows, `tty` on Unix) -- captures approval input

### Request Flow

1. AI agent calls a tool (e.g., `Read("src/db.py")`)
2. Hook script reads `.consurg-guard.lock` to find the guard port
3. Hook sends `POST /evaluate` with tool name and file path
4. Guard resolves the file's tier against the live scope
5. If allowed: returns `{"decision": "allow"}`, logs the event
6. If denied and interactive: blocks the HTTP response, shows approval prompt in TUI
7. User presses a key to approve or deny
8. Guard returns the decision, hook exits with code 0 (allow) or 2 (deny)

### Approval Timeout

When a blocked access triggers an approval prompt, the guard waits **8 seconds** for user input. This is derived from Claude Code's 10-second hook timeout minus a 2-second safety margin.

If no input is received within 8 seconds, the access is **denied by default**.

## Approval Keys

When the approval prompt appears:

| Key | Action | Effect |
|-----|--------|--------|
| `W` | Working set | Promote file to T4 (full read-write) |
| `R` | Read-only | Promote file to T3 (read-only) |
| `S` | Signature | Promote file to T2 (signature-only) |
| `D` | Deny | Block access, do not promote |

Promotions are **persistent for the guard session**. Once you promote a file, subsequent accesses to that file are automatically allowed at the promoted tier.

## Other Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `Q` | Quit the guard |

## Access Log Icons

| Icon | Meaning |
|------|---------|
| Green checkmark | Access allowed |
| Red X | Access denied |
| Yellow arrow | Access allowed after user promotion |

## Lockfile

The guard writes `.consurg-guard.lock` in the project root when it starts. This file contains:

```json
{
  "pid": 12345,
  "port": 9876,
  "scope": "auth-refactor"
}
```

Hook scripts read this file to discover the guard's port. Stale lockfiles (where the PID is no longer running) are ignored.

The lockfile is automatically removed when the guard stops.

## Headless Guard via `wrap`

For one-shot enforcement without a persistent guard:

```bash
consurg wrap -- claude "fix the auth bug"
```

This:
1. Starts a headless guard on a random port
2. Writes the lockfile
3. Sets `CONSURG_GUARD_PORT` and `CONSURG_ACTIVE=1` in the subprocess environment
4. Runs the command
5. Stops the guard and removes the lockfile when the command exits

The wrapped command's exit code is propagated.

## HTTP API

The guard server exposes three endpoints on `127.0.0.1`:

### `POST /evaluate`

Evaluate a tool access request.

**Request:**
```json
{
  "tool_name": "Read",
  "file_path": "src/db.py",
  "tool_input": {}
}
```

**Response (allow):**
```json
{
  "decision": "allow",
  "tier": 4,
  "label": "READ-WRITE"
}
```

**Response (deny):**
```json
{
  "decision": "deny",
  "tier": 0,
  "label": "BLOCKED",
  "message": "[CONTEXT SURGEON] access denied: src/db.py (Tier 0 BLOCKED)"
}
```

### `GET /health`

```json
{
  "status": "ok",
  "uptime": 123.45
}
```

### `GET /log`

Returns the last 50 access events:

```json
{
  "events": [
    {
      "timestamp": 1707500000.0,
      "tool": "Read",
      "file": "src/auth.py",
      "tier": 4,
      "label": "READ-WRITE",
      "decision": "allow"
    }
  ]
}
```

## Fallback Behavior

If the guard is not running (no lockfile, or lockfile points to a dead PID), the hook falls back to **direct enforcement** using the same tier resolution logic. The agent is still restricted by the scope -- you just don't get the interactive TUI.
