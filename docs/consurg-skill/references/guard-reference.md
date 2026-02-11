# Guard Reference

The guard is a real-time scope firewall that intercepts every file access from the AI agent. It runs as a local HTTP server with an optional Rich TUI dashboard.

## Starting the Guard

```bash
consurg guard -i                    # Interactive TUI (default)
consurg guard --no-tui              # Headless (server only)
consurg guard -i --port 8888        # Custom port (default: 9876)
```

## Architecture

Three threads, zero new dependencies (all stdlib + Rich):

```
+------------------+     +-----------------+     +----------------+
|  HTTP Server     |     |  Guard State    |     |  TUI           |
|  (daemon thread) +---->+  (thread-safe)  +<----+  (main thread) |
+------------------+     +--------+--------+     +----------------+
                                  ^
                         +--------+--------+
                         |  Keyboard       |
                         |  (daemon thread)|
                         +-----------------+
```

- **HTTP server thread**: `http.server.HTTPServer`, handles `/evaluate`, `/health`, `/log`
- **TUI thread**: Rich `Live` with `Layout`, renders at 4 FPS
- **Keyboard thread**: `msvcrt.getwch()` (Windows) or `tty.setraw()` + `select()` (Unix)

## Request Flow

1. Agent calls a tool (e.g., `Read("src/db.py")`)
2. Hook reads `.consurg-guard.lock` to find guard port
3. Hook sends `POST /evaluate` with tool name and file path
4. Guard resolves the file's tier against the live scope
5. If allowed: returns `{"decision": "allow"}`, logs event
6. If denied + interactive: blocks HTTP response, shows TUI approval prompt
7. User presses a key to approve or deny
8. Guard returns decision, hook exits with code 0 or 2

## Approval Keys

| Key | Action | Effect |
|-----|--------|--------|
| `W` | Working set | Promote file to T4 (full read-write) |
| `R` | Read-only | Promote file to T3 (read-only) |
| `S` | Signature | Promote file to T2 (signature-only) |
| `D` | Deny | Block access, do not promote |
| `Q` | Quit | Stop the guard |

Promotions persist for the guard session. Subsequent accesses to a promoted file are auto-allowed.

## Approval Timeout

The guard waits **8 seconds** for user input (derived from Claude Code's 10-second hook timeout minus 2-second safety margin). No input within 8 seconds results in denial.

## HTTP API

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
{"status": "ok", "uptime": 123.45}
```

### `GET /log`

Returns the last 50 access events as JSON array.

## Lockfile Protocol

The guard writes `.consurg-guard.lock` in the project root:

```json
{
  "pid": 12345,
  "port": 9876,
  "scope": "auth-refactor"
}
```

Hook scripts read this file to discover the guard port. Stale lockfiles (dead PID) are ignored. PID liveness checked cross-platform: `ctypes.windll.kernel32.OpenProcess()` on Windows, `os.kill(pid, 0)` on Unix.

Lockfile is automatically removed when the guard stops.

## Headless Guard via `wrap`

```bash
consurg wrap -- claude "fix the auth bug"
```

This:
1. Starts a headless guard on a random free port
2. Writes the lockfile
3. Sets `CONSURG_GUARD_PORT` and `CONSURG_ACTIVE=1` in subprocess environment
4. Runs the command
5. Stops guard and removes lockfile when command exits

Exit code from the wrapped command is propagated.

## Fallback Behavior

If the guard is not running (no lockfile or dead PID), hooks fall back to **direct enforcement** using the same `resolve_tier()` logic. The agent is still restricted by `.consurg.yaml`, just without interactive approvals.

## Thread Safety

`GuardState` uses `threading.Lock` for all mutations:
- `add_event()` -- appends to access log deque (500-item rolling buffer)
- `set_pending()` / `clear_pending()` -- manages approval request
- `promote_file()` -- modifies live scope tier lists
- `tier_counts()` -- reads tier list lengths

`ApprovalRequest.event` is a `threading.Event` signaling the HTTP thread when keyboard input arrives.

## GuardState Data Model

```python
@dataclass
class GuardState:
    scope: Scope
    interactive: bool
    port: int
    access_log: deque[AccessEvent]    # 500-item rolling buffer
    pending: ApprovalRequest | None   # Current approval waiting for user
    auto_approved: dict[str, int]     # file -> tier (from promotions)
    lock: threading.Lock
    running: bool
    start_time: float

@dataclass
class AccessEvent:
    timestamp: float
    tool_name: str
    file_path: str
    tier: int
    label: str
    decision: str       # "allow" or "deny"
    promoted: bool      # True if promoted during this request

@dataclass
class ApprovalRequest:
    tool_name: str
    file_path: str
    tier: int
    label: str
    event: threading.Event
    response: str | None      # "w"=T4, "r"=T3, "s"=T2, "d"=deny
    promoted_tier: int | None
```
