# Context Surgeon

**One scope, two outputs.** Pick the files that matter for your task — with a tier for each — and point that selection wherever you need it:

1. **Enforce it** — run an AI coding agent (Claude Code, Codex, Gemini CLI, …) that can *only* see your selection. Everything else is blocked at the tool layer, live.
2. **Render it** — compose the same selection into a paste-ready context blob for ChatGPT, Claude, or any chat LLM. Full content for working files, extracted signatures for interfaces, nothing for the rest.

The selection is the **scope** (`.consurg.yaml`): a temporary, tiered boundary around the files that matter. Demote a file to signatures-only and it *both* hides its implementation from the live agent *and* shrinks to type stubs in the pasted prompt.

## Install

```bash
git clone https://github.com/kingkillery/consurg.git
cd consurg
pip install -e .

consurg --help
```

**Requirements:** Python 3.10+. Dependencies: `typer`, `rich`, `pyyaml` (installed automatically).

## Quick Start

### 1. Pick your files

```bash
cd your-project
consurg pick
```

Running `consurg` with no subcommand opens the same picker interactively, starting at `C:/dev` when that folder exists. It provides a searchable filesystem tree, keyboard navigation, and per-file **RW**, **RO**, **SIG**, and **LIST** tiers (plus **OFF** to clear a selection). Use `consurg pick` to start in the current directory, or `consurg pick --root C:/dev` to choose another starting folder.

Opens a local-only browser UI with nested native lists, disclosure buttons, and checkboxes. Start in the current repo or use **Choose folder** to switch to any local folder, then set each selected file's tier. Keyboard focus stays on the control you changed when the list updates:

| Toggle | Tier | Live agent gets | Pasted prompt gets |
|--------|------|-----------------|--------------------|
| **RW** | T4 | read + write | full content |
| **RO** | T3 | read only | full content |
| **SIG** | T2 | signatures only | extracted function/class signatures |
| **LIST** | T1 | path/name only | listed in the file tree, no content |
| **OFF** | T0 | nothing | nothing |

Token counts update live per file and in total.

If saving a scope would expand wildcard entries into explicit paths, the picker explains the change and requires confirmation before saving.

### 2a. …then paste it into ChatGPT

In the UI: add optional task instructions, choose markdown/xml/plain, then hit **Copy + open ChatGPT**. The generated context is copied to your clipboard for you to paste into ChatGPT; files are never uploaded by Consurg. Or from the CLI once a scope is saved:

```bash
consurg copy                        # print the rendered context
consurg copy --clip                 # straight to clipboard
consurg copy -f xml -t "fix login"  # xml format, task prepended
```

### 2b. …or run an agent inside it

Hit **Save scope** in the UI (writes `.consurg.yaml`), then:

```bash
consurg run claude "fix the auth bug"
```

One command: wires Claude Code's hooks, starts a headless guard, launches the tool, unwires and cleans up when it exits. The agent physically cannot read or edit anything outside your selection — a blocked file returns a structured denial, not silence.

Works with `claude`, `codex`, `gemini`, `droid`, `pk-agent`, or any command (guard-only if there's no wirer for it).

### Watching it live (optional)

Prefer to approve boundary crossings interactively? Run the guard TUI in a second terminal instead:

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

## The Tier Model

| Tier | Label | Permissions | Scope Key |
|------|-------|-------------|-----------|
| **T4** | READ-WRITE | Full read and write access | `working_set` |
| **T3** | READ-ONLY | Can read, cannot write | `reference` |
| **T2** | SIGNATURE | Function/class signatures only | `signatures` |
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

You can edit this by hand, build it in the picker UI, or generate it:

```bash
consurg trace src/main.py --depth 1   # scope from the import graph
consurg git-diff                      # scope from changed files
consurg add "src/auth/*.py"           # add patterns directly (--read, --sig)
```

## All Commands

### The daily three

| Command | Purpose |
|---------|---------|
| `consurg pick` | Local browser UI: choose a folder, check files in a tree, copy context to ChatGPT, save the scope |
| `consurg copy [--clip] [-f FMT] [-t TASK]` | Render the scope as a paste-ready prompt (markdown, xml, plain) |
| `consurg run TOOL [ARGS...]` | Wire + guard + launch a tool under the scope, clean up on exit |
| `consurg snap FILES [--read P] [--sig P] [--clip] [-o FILE] [-t TASK]` | One-shot context render for an ad-hoc file selection — no scope file needed or touched |

### Scope management

| Command | Purpose |
|---------|---------|
| `consurg init [name]` | Create `.consurg.yaml` with default tiers |
| `consurg add FILES [--read] [--sig]` | Add patterns to a tier |
| `consurg remove FILES` | Remove patterns from all tiers |
| `consurg on` / `off` | Activate or deactivate scope |
| `consurg status` | Show tier counts, patterns, and wired tools |
| `consurg map [--scoped-only] [--depth N]` | Visualize files as a tree with tier badges |
| `consurg trace ENTRIES [--depth N] [--apply]` | Build scope from dependency graph |
| `consurg git-diff [BASE] [--apply]` | Build scope from branch diff |
| `consurg pin` / `unpin` | Save or remove scope file |
| `consurg clean [--keep-scope]` | Deactivate scope, unwire all tools, remove scope file |

### Advanced / plumbing

| Command | Purpose |
|---------|---------|
| `consurg guard [-i] [--port N] [--no-tui]` | Start the interactive scope firewall manually |
| `consurg wire TOOL [--unwire]` | Manually configure hooks for a tool (`run` does this for you) |
| `consurg wrap -- CMD [ARGS]` | Run a command under a headless guard (no wiring) |
| `consurg export --format FMT` | Export scope *rules* as claude, cursor, aider, or generic |
| `consurg file-context [--print]` | Legacy flat file picker (superseded by `pick`) |
| `consurg audit-status` | Show effective audit config and local audit storage usage |
| `consurg scaffold-pk-agents [--force]` | Create pk-agent scope selector + excluded-context summarizer |
| `consurg apply-proposal [--apply]` | Map scope-proposal output into `.consurg.yaml` |

## Supported Tools

| Tool | Wire Method |
|------|-------------|
| **Claude Code** | PreToolUse hook in `.claude/hooks.json` |
| **pk-agent** | `tool:start` hook in `.pk-agent/hooks.json` |
| **PuzlD AI (droid)** | Trusted dirs in `~/.puzldai/trusted-dirs.json` |
| **Gemini CLI** | MCP server wrapper in `~/.gemini/mcp_config.json` |
| **Codex CLI** | MCP server wrapper in `~/.codex/mcp.json` |

`consurg run <tool>` wires and unwires automatically. For a persistent setup use `consurg wire <tool>` / `consurg wire <tool> --unwire`; `consurg status` shows what's currently wired.

## Rendered Output

`consurg copy` (and the picker's **Copy + open ChatGPT**) produce:

````markdown
# Context: auth-refactor

## Task
fix the login timeout

## Files
```
src/auth.py      [RW]
src/config.py    [RO]
src/types.py     [SIG]
```

## FILE: src/auth.py (read-write)
...full content...

## SIGNATURES: src/types.py (signatures)
class User:
def make_user(name):
````

Oversized files, binary files, and `never_include` matches are listed in an `## Omitted` section rather than dropped silently. Limits are configurable in `.consurg.yaml`:

```yaml
file_context_ui:
  never_include: [".env", "secrets/**"]
  max_file_bytes: 20000
  max_total_bytes: 200000
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

# Run tests
python -m pytest tests/ -v
```

## License

MIT
