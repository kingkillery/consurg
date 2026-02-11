# Wire System Reference

The wire system auto-configures hooks and integrations for supported AI tools. One command to connect, one to disconnect.

## Usage

```bash
consurg wire <tool>            # Install hooks
consurg wire <tool> --unwire   # Remove hooks
```

All wirers are idempotent. Running `wire` twice does not create duplicates. Running `unwire` only removes consurg entries, preserving other configuration.

## Supported Tools

### Claude Code

```bash
consurg wire claude
```

Creates `.claude/hooks.json` with a `PreToolUse` hook:

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

Preserves existing hooks. Claude Code runs the hook before every tool call.

### pk-agent

```bash
consurg wire pk-agent
```

Creates `.pk-agent/hooks.json` with a `tool:start` hook:

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

Adds a consurg-marked entry to `~/.puzldai/trusted-dirs.json`:

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

### Gemini CLI

```bash
consurg wire gemini
```

Generates two artifacts:
1. MCP server wrapper at `hooks/consurg_mcp_gemini.py`
2. Entry in `~/.gemini/mcp_config.json`:

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

Gemini CLI lacks native hooks, so the MCP wrapper acts as a proxy intercepting tool calls.

### Codex CLI

```bash
consurg wire codex
```

Same pattern as Gemini. Generates `hooks/consurg_mcp_codex.py` and registers in `~/.codex/mcp.json`.

## Wire Architecture

Three integration strategies based on tool capabilities:

| Strategy | Tools | Mechanism |
|----------|-------|-----------|
| **Hook-based** | Claude Code, pk-agent | Project-level hooks.json |
| **Config-based** | droid | User-level trusted-dirs.json |
| **MCP-based** | Gemini, Codex | Generated MCP wrapper + user-level config |

### BaseWirer Interface

All wirers implement this abstract base class:

```python
class BaseWirer(ABC):
    def __init__(self, project_dir: str | Path | None = None):
        self.project_dir = Path(project_dir) if project_dir else Path.cwd()
        self.hook_script = self._find_hook_script()

    @property
    @abstractmethod
    def name(self) -> str: ...       # Human-readable tool name

    @abstractmethod
    def wire(self) -> WireResult: ... # Install hooks/config

    @abstractmethod
    def unwire(self) -> WireResult: ... # Remove hooks/config

    @abstractmethod
    def status(self) -> str: ...     # "wired", "not wired", "partial"
```

### WireResult

Return type for `wire()` and `unwire()`:

```python
@dataclass
class WireResult:
    success: bool
    message: str
    config_path: Path | None = None
```

## Guard Integration

All hook scripts follow a dual-path strategy:

1. Check for `.consurg-guard.lock` in project root
2. If found and guard reachable: `POST /evaluate` to guard (interactive approval)
3. If guard unreachable: fall back to direct scope enforcement (silent tier logic)

This means:
- **Guard running:** Real-time access log, interactive approval, live tier promotion
- **Guard not running:** Silent enforcement from `.consurg.yaml` (same logic, no interactivity)

## Status Detection

After wiring, current status is displayed:

```
Wired to Claude Code (PreToolUse hook)
Config: /path/to/project/.claude/hooks.json
Status: wired
```

Possible statuses:
- `wired` -- hooks installed and functional
- `not wired` -- no consurg hooks found
- `partial` -- config exists but wrapper script missing (Gemini/Codex only)
