---
name: context-surgeon
description: >-
  This skill should be used when the user asks to "create a scope",
  "restrict agent access", "set up consurg", "scope files",
  "add files to working set", "wire consurg to Claude",
  "wire consurg to Codex", "wire consurg to Gemini",
  "start the guard", "trace dependencies", "build scope from git diff",
  "export scope", "narrow scope for subagent", "check scope status",
  "limit what Claude can see", "restrict file access",
  "set up file permissions for agent", "protect files from agent edits",
  "block files from agent", "promote a file", "unblock a file",
  "show what files the agent can access", "scope my project",
  "export scope for cursor", "export scope for aider",
  "run with scope enforcement", "consurg", "pin my scope",
  or needs to manage file-level access control for AI coding agents
  using Context Surgeon's 5-tier permission model.
version: 0.2.0
allowed-tools: Read, Write, Edit, Bash, Glob, Grep
---

# Context Surgeon

Context Surgeon temporarily restricts AI coding agents to a declared subset of files using a 5-tier permission model. Instead of building context from scratch, it restricts an agent's view to only the files relevant to the current task. The result: fewer mistakes, faster sessions, and no unintended edits outside the working set.

## Core Concept: 5-Tier Access Model

| Tier | Label | Agent Access | Scope Key |
|------|-------|-------------|-----------|
| **T4** | READ-WRITE | Full read and write | `working_set` |
| **T3** | READ-ONLY | Read content, no writes | `reference` |
| **T2** | SIGNATURE | Function/class headers only | `signatures` |
| **T1** | EXISTENCE | Filename only, no content | `visible` |
| **T0** | BLOCKED | Invisible (default) | _(implicit)_ |

Tier 2 is the key innovation: semantic compression that preserves API surface (like `.d.ts` or `.pyi` stubs) while cutting implementation noise.

For detailed tier behavior, tool-tier matrix, and edge cases, consult **`references/tier-model.md`**.

## Installation

```bash
pip install -e /path/to/consurg
consurg --help
```

Requirements: Python 3.10+. Dependencies (`typer`, `rich`, `pyyaml`) install automatically.

## Essential Workflow

### 1. Initialize and populate a scope

```bash
consurg init my-feature
consurg add "src/auth/*.py" "tests/test_auth.py"         # T4 read-write
consurg add --read "src/core/*.py" "docs/*.md"            # T3 read-only
consurg add --sig "types/*.pyi"                           # T2 signatures
consurg on
```

### 2. Wire to an AI tool

```bash
consurg wire claude        # Claude Code (PreToolUse hook)
consurg wire codex         # OpenAI Codex CLI (MCP wrapper)
consurg wire gemini        # Google Gemini CLI (MCP wrapper)
consurg wire pk-agent      # pk-agent (tool:start hook)
consurg wire droid         # PuzlD AI (trusted-dirs config)
```

Remove with `consurg wire <tool> --unwire`. All operations are idempotent.

### 3. Enforce interactively or headlessly

```bash
# Interactive TUI guard (real-time access log + approval prompts)
consurg guard -i

# One-shot wrapped command (headless guard, auto-cleanup)
consurg wrap -- claude "fix the auth bug in src/auth.py"
```

### 4. Deactivate when done

```bash
consurg off                       # Stop enforcement
consurg wire claude --unwire      # Remove hooks
```

## Auto-Building Scopes

### From dependency tracing

```bash
consurg trace src/auth/login.py --depth 3 --apply
```

Traces Python/TypeScript imports via BFS. Entry files get T4, direct deps T3, transitive deps T2. Supports Python AST-based resolution and TypeScript regex-based resolution with tsconfig path aliases.

### From git diff

```bash
consurg git-diff main --apply
```

Changed files get T4, their direct dependencies get T3. Auto-detects `main`/`master` if no base specified.

For full trace engine documentation, consult **`references/trace-reference.md`**.

## Inspection Commands

```bash
consurg status              # Tier counts, patterns, active state
consurg map                 # Full project tree with tier badges [RW] [RO] [SIG] [--]
consurg export --format X   # Export as: claude, cursor, aider, generic
```

## CLI Quick Reference

| Command | Purpose |
|---------|---------|
| `consurg init [name]` | Create `.consurg.yaml` |
| `consurg add FILES [--read] [--sig]` | Add patterns to a tier |
| `consurg remove FILES` | Remove patterns from all tiers |
| `consurg on` / `off` | Activate/deactivate enforcement |
| `consurg status` | Show scope details |
| `consurg map` | Visualize file tree with tier badges |
| `consurg trace ENTRIES [--depth N] [--apply]` | Build scope from imports |
| `consurg git-diff [BASE] [--apply]` | Build scope from branch diff |
| `consurg export --format FMT` | Export scope (claude/cursor/aider/generic) |
| `consurg guard [-i] [--port N] [--no-tui]` | Start interactive guard |
| `consurg wire TOOL [--unwire]` | Auto-configure hooks for a tool |
| `consurg wrap -- CMD [ARGS]` | Run command with embedded enforcement |

For full flags, options, and exit codes, consult **`references/cli-reference.md`**.

## Scope File Format (.consurg.yaml)

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
```

Patterns use `fnmatch` (shell-style wildcards) with forward slashes (`/`) as separators, even on Windows. First matching pattern wins, checked T4 through T1. Everything unmatched defaults to T0 BLOCKED.

Set `explorer: true` to allow all reads while still restricting writes. Useful during investigation phases before narrowing the scope.

For the full schema and advanced fields, consult **`references/scope-schema.md`**.

## Guard System

The interactive guard is an HTTP server that intercepts file access in real time via a lockfile-based rendezvous protocol. Three threads (HTTP server, TUI renderer, keyboard listener) coordinate through thread-safe shared state. Approval keys: `W` (promote to T4), `R` (T3), `S` (T2), `D` (deny). Timeout: 8 seconds.

For architecture details, HTTP API, and approval flow, consult **`references/guard-reference.md`**.

## Hook Protocol

Hooks follow the Claude Code PreToolUse contract: JSON on stdin, exit 0 (allow) or exit 2 (deny with structured stderr JSON). The dual-path hook (`enforce_guard.py`) tries the guard server first, falls back to direct enforcement.

Without the guard running, if access is denied, edit `.consurg.yaml` directly to add the file to the appropriate tier. The hook re-reads the scope file on every tool call, so changes take effect immediately.

For the full protocol spec and custom hook guide, consult **`references/hook-protocol.md`**.

## Programmatic API

```python
from consurg.scope import Scope, ScopeError, load_scope, narrow_scope, detect_write_conflicts
from consurg.enforce import resolve_tier
from consurg.trace import DependencyGraph, resolve_python_imports, resolve_ts_imports, extract_signatures
from consurg.adapters import generate_claude_scope, generate_cursor_rules, generate_aider_args, generate_generic_prompt
```

Key operations:
- `resolve_tier(path, scope)` returns `(tier_int, label_str)`
- `narrow_scope(parent, file_list)` creates child scopes for subagents
- `detect_write_conflicts([scope_a, scope_b])` finds overlapping T4 patterns
- `DependencyGraph().classify_tiers(entries)` returns `{file: tier}` mapping

## When NOT to Use

- **Exploratory tasks** requiring broad codebase access
- **Cross-cutting refactors** that touch every file
- **Bug investigation before localization** (explore first, scope after)
- **Small projects** where total tokens < 10x working set tokens

**Two-phase rule:** Explore unscoped, execute scoped. Never skip exploration.

## Slash Commands

| Command | Description |
|---------|-------------|
| `/consurg-scope` | Show the active scope with files organized by tier |
| `/consurg-scope-status` | Run `consurg status` and display tier counts |
| `/consurg-scope-map` | Run `consurg map` and display the tier-annotated file tree |

## Additional Resources

### Reference Files

For detailed documentation beyond this overview:

- **`references/tier-model.md`** -- Tier behavior, tool-tier matrix, explorer mode, drift detection, scope narrowing
- **`references/cli-reference.md`** -- Complete CLI with all flags, options, and exit codes
- **`references/guard-reference.md`** -- Guard architecture, HTTP API, approval flow, lockfile protocol
- **`references/wire-reference.md`** -- Wire system for all 5 supported tools, idempotency, MCP wrappers
- **`references/trace-reference.md`** -- Dependency tracing, Python/TypeScript resolvers, graph API
- **`references/hook-protocol.md`** -- Hook contract, denial messages, custom hook guide
- **`references/scope-schema.md`** -- Full `.consurg.yaml` schema and pattern matching rules
- **`references/export-adapters.md`** -- Export format details, output examples, programmatic API
- **`references/architecture.md`** -- System design, threading model, data flow diagrams

### Example Files

Working examples in `examples/`:

- **`examples/basic-scope.yaml`** -- Minimal scope file template
- **`examples/auth-refactor-workflow.sh`** -- End-to-end auth refactor workflow
- **`examples/trace-workflow.sh`** -- Auto-scope via dependency tracing
- **`examples/custom-hook.py`** -- Writing a custom enforcement hook
- **`examples/multi-agent-narrowing.py`** -- Scope narrowing for multi-agent setups

### Utility Scripts

Cross-platform Python scripts (Windows, macOS, Linux) in `scripts/`:

- **`scripts/validate_scope.py`** -- Validate `.consurg.yaml` structure, types, patterns, and duplicates
- **`scripts/quick_scope.py`** -- Interactive scope setup helper with T1-T4 prompts
- **`scripts/check_install.py`** -- Verify consurg installation, dependencies, and imports
