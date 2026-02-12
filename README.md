# Context Surgeon

Temporarily restrict AI coding agents to a declared subset of files. Define what an agent can read, write, and see — enforce it in real time.

```
Terminal 1: consurg guard -i          Terminal 2: claude "fix auth bug"
+--------------------------------+
| GUARD: auth-refactor [ACTIVE]  |    Claude calls Read("src/db.py")
| Port: 9876  T4:3 T3:2 T2:0    |         |
|--------------------------------|         v
| ACCESS LOG                     |    hook/enforce_guard.py
| 14:03:01 Read  src/auth.py  T4 |    -> POST localhost:9876/evaluate
| 14:03:03 Edit  src/auth.py  T4 |         |
| 14:03:05 Read  src/db.py    T0 |    <- {"decision":"deny"}
|--------------------------------|         |
| APPROVAL: src/db.py (T0)      |    Guard prompts user in TUI:
| [W]orking [R]ead-only [D]eny  |    User presses 'r' -> promote to T3
|--------------------------------|    -> scope updated, allow returned
| 14:03:05 Read  src/db.py    T3 |    Claude proceeds with read
+--------------------------------+
```

## Install

```bash
# Clone and install
git clone https://github.com/kingkillery/consurg.git
cd consurg
pip install -e .

# Verify
consurg --help
```

**Requirements:** Python 3.10+. No external dependencies beyond `typer`, `rich`, and `pyyaml` (installed automatically).

## Quick Start

### 1. Create a scope

```bash
cd your-project
consurg init my-feature
```

This creates `.consurg.yaml` in your project root.

### 2. Define access tiers

```bash
# Files the agent can read AND write (Tier 4)
consurg add "src/auth/*.py" "tests/test_auth.py"

# Files the agent can read but not write (Tier 3)
consurg add --read "src/core/*.py" "docs/*.md"

# Files the agent can see signatures only (Tier 2)
consurg add --sig "types/*.pyi"
```

### 3. Wire to your AI tool

```bash
# Claude Code
consurg wire claude

# Or: pk-agent, droid, gemini, codex
consurg wire gemini
```

### 4. Start the interactive guard

```bash
consurg guard -i
```

The TUI shows every file access in real time. When the agent tries to access a blocked file, you're prompted to approve or deny — without leaving your terminal.

### 5. Or wrap a single command

```bash
consurg wrap -- claude "fix the auth bug in src/auth.py"
```

Starts a headless guard, runs the command with scope enforcement, cleans up when done.

## The Tier Model

| Tier | Label | Permissions | Scope Key |
|------|-------|-------------|-----------|
| **T4** | READ-WRITE | Full read and write access | `working_set` |
| **T3** | READ-ONLY | Can read, cannot write | `reference` |
| **T2** | SIGNATURE | Can view function/class signatures | `signatures` |
| **T1** | EXISTENCE | Can reference by name only | `visible` |
| **T0** | BLOCKED | No access (default for unlisted files) | _(implicit)_ |

Higher tiers take precedence. First matching pattern wins. Patterns use shell-style wildcards (`fnmatch`).

## Scope File Format

`.consurg.yaml`:

```yaml
version: 1
scope: auth-refactor
active: true
reason: "Restricting agent to auth module"
working_set:
  - src/auth/*.py
  - tests/test_auth.py
reference:
  - src/core/*.py
  - docs/auth.md
signatures:
  - types/*.pyi
visible:
  - config.yaml
dynamic_deps: []
explorer: false
```

## All Commands

| Command | Purpose |
|---------|---------|
| `consurg init [name]` | Create `.consurg.yaml` with default tiers |
| `consurg add FILES [--read] [--sig]` | Add patterns to a tier |
| `consurg remove FILES` | Remove patterns from all tiers |
| `consurg on` / `off` | Activate or deactivate scope |
| `consurg status` | Show tier counts and patterns |
| `consurg audit-status` | Show effective audit config and local audit storage usage |
| `consurg clean [--keep-scope]` | Deactivate scope, unwire all tools, and remove scope file |
| `consurg map [--scoped-only] [--depth N]` | Visualize files as a tree with tier badges |
| `consurg trace ENTRIES [--depth N] [--apply]` | Build scope from dependency graph |
| `consurg git-diff [BASE] [--apply]` | Build scope from branch diff |
| `consurg export --format FMT` | Export as claude, cursor, aider, or generic |
| `consurg guard [-i] [--port N] [--no-tui]` | Start interactive scope firewall |
| `consurg wire TOOL [--unwire]` | Auto-configure hooks for a tool |
| `consurg wrap -- CMD [ARGS]` | Run command with embedded scope enforcement |
| `consurg scaffold-pk-agents [--force]` | Create pk-agent scope selector + excluded-context summarizer |
| `consurg apply-proposal [--proposal-file PATH] [--apply]` | Map scope-proposal output into `.consurg.yaml` |
| `consurg pin` / `unpin` | Save or remove scope file |

## Supported Tools

| Tool | Wire Method | Command |
|------|-------------|---------|
| **Claude Code** | PreToolUse hook in `.claude/hooks.json` | `consurg wire claude` |
| **pk-agent** | `tool:start` hook in `.pk-agent/hooks.json` | `consurg wire pk-agent` |
| **PuzlD AI (droid)** | Trusted dirs in `~/.puzldai/trusted-dirs.json` | `consurg wire droid` |
| **Gemini CLI** | MCP server wrapper in `~/.gemini/mcp_config.json` | `consurg wire gemini` |
| **Codex CLI** | MCP server wrapper in `~/.codex/mcp.json` | `consurg wire codex` |

Unwire with `consurg wire <tool> --unwire`.

## pk-agent Scope Automation

Create the two-agent system for scope planning and excluded-context review:

```bash
consurg scaffold-pk-agents
```

This generates:
- `.agents/pk-agents/consurg-scope-selector.pk-agent`
- `.agents/pk-agents/consurg-excluded-summarizer.pk-agent`
- `.agents/pk-agents/README.md` (runbook)

Apply proposal output into Consurg tiers:

```bash
consurg apply-proposal --apply
```

Install dependency if needed:

```bash
npm i -g pk-agent
```

## Documentation

Detailed documentation is in the [`docs/`](docs/) directory:

- **[Getting Started](docs/getting-started.md)** -- Installation, first scope, basic workflow
- **[Tier Model](docs/tiers.md)** -- How the 5-tier access model works
- **[Interactive Guard](docs/guard.md)** -- TUI firewall, headless mode, approval flow
- **[Wire System](docs/wire.md)** -- Auto-configuring hooks for each supported tool
- **[Hook System](docs/hooks.md)** -- How enforcement hooks work, dual-path guard hook
- **[Dependency Tracing](docs/trace.md)** -- Auto-building scopes from imports and git diffs
- **[Export Adapters](docs/adapters.md)** -- Generating tool-specific scope formats
- **[CLI Reference](docs/cli-reference.md)** -- Full reference for every command and option
- **[Architecture](docs/architecture.md)** -- System design, threading model, data flow
- **[pk-agent Audit Integration](docs/pk-agent-audit-integration.md)** -- Opt-in hardened audit telemetry contract (redaction + retention)

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests (176 tests)
python -m pytest tests/ -v

# Run a specific test file
python -m pytest tests/test_guard.py -v
```

## License

MIT
