---
name: context-surgeon
description: Temporarily restrict AI coding agents to a declared subset of files using a 5-tier permission model
allowed-tools: Read, Write, Edit, Bash, Glob, Grep
---

# Context Surgeon

Context Surgeon is a subtractive context management tool for AI coding agents. Instead of building context from scratch (additive), it restricts an agent's view to only the files that matter for the current task (subtractive). The result: fewer mistakes, faster sessions, and no unintended edits outside your working set.

## The 5-Tier Permission Model

| Tier | Label | Agent Sees | Use Case |
|------|-------|-----------|----------|
| 0 | **Blocked** | Nothing. File does not exist. | Unrelated modules, secrets, `.env` |
| 1 | **Existence** | Filename in directory listings only. No content. | Project structure awareness |
| 2 | **Signature** | Type definitions, function headers, class interfaces. No implementation. | Shared types, API contracts, interfaces |
| 3 | **Read-only** | Full file content. Cannot modify. | Config, manifests, test fixtures |
| 4 | **Read-write** | Full access. | The working set (files being edited) |

Tier 2 is the key innovation: context compression that preserves semantic information. The agent gets enough to reason about types and contracts without implementation noise. Same principle as `.d.ts` (TypeScript) or `.pyi` (Python) stub files.

## Quick Start

### 1. Initialize a scope

```bash
consurg init my-feature
```

Creates `.consurg.yaml` in the project root with an empty scope.

### 2. Add files to the working set

```bash
# Tier 4 (read-write) - your working files
consurg add src/parser.py src/helpers/*.py

# Tier 3 (read-only) - reference files
consurg add --read pyproject.toml src/config.py

# Tier 2 (signature-only) - type/interface files
consurg add --sig src/shared_types.py
```

### 3. Activate enforcement

```bash
consurg on
```

The scope is now active. The enforcement hook blocks out-of-scope file access with structured denial messages.

### 4. Work within scope

The agent operates inside the declared boundary. Out-of-scope access attempts produce structured denials with recovery instructions, not silent failures.

### 5. Deactivate when done

```bash
consurg off
```

Full codebase access is restored.

## Common Workflows

### Focused feature work

```bash
consurg init auth-fix
consurg add src/auth.py src/middleware.py src/session.py
consurg add --read src/config.py src/models/user.py
consurg on
# ... do the work ...
consurg off
```

### Dependency trace (Phase 3)

```bash
consurg trace src/parser.py --depth 1
```

Auto-discovers imports from the entry point file and classifies each dependency by tier:
- `TYPE_CHECKING` imports become Tier 2 (signature)
- Value imports become Tier 3 (read-only)
- Side-effect imports become Tier 1 (existence)
- Dynamic imports are flagged for user decision

### Git-diff scoping (Phase 3)

```bash
consurg git-diff            # scope to uncommitted changes
consurg git-diff HEAD~3     # scope to last 3 commits
```

### Scope visualization

```bash
consurg map
```

Displays a tier-annotated file tree:
```
src/
  parser.py            [RW] ██████
  parser_helpers/
    a.py               [RW] ██████
  shared_types.py      [SIG] ░░░░
  config.py            [RO] ▒▒▒▒
  formatter.py         [--] ----
```

### Scope status

```bash
consurg status
```

Shows active scope details: name, active/inactive state, tier counts, and patterns.

### Persist across sessions

```bash
consurg pin     # write .consurg.yaml for multi-day work
consurg unpin   # remove persisted scope
```

## CLI Reference

| Command | Description |
|---------|-------------|
| `consurg init [name]` | Create a new scope (defaults to directory name) |
| `consurg on` | Activate the current scope |
| `consurg off` | Deactivate the current scope |
| `consurg status` | Show active scope details with tier counts |
| `consurg map` | Visualize scope as a tier-annotated directory tree |
| `consurg add <files...>` | Add files to working set (Tier 4) |
| `consurg add --read <files...>` | Add files as read-only (Tier 3) |
| `consurg add --sig <files...>` | Add files as signature-only (Tier 2) |
| `consurg remove <files...>` | Remove file patterns from all tiers |
| `consurg pin` | Persist scope to `.consurg.yaml` |
| `consurg unpin` | Remove persisted `.consurg.yaml` |
| `consurg trace <entry> [--depth N]` | Auto-discover scope from imports (Phase 3) |
| `consurg git-diff [ref]` | Scope to changed files (Phase 3) |
| `consurg enforce` | (Internal) Validate a tool call against scope |
| `consurg adapt <tool>` | Generate scope config for a specific tool (Phase 4) |

## Scope File Format (.consurg.yaml)

```yaml
version: 1
scope: "parser-refactor"
active: true
reason: "Refactoring parser pipeline"

working_set:              # Tier 4: read-write
  - src/parser.py
  - src/parser_helpers/*.py

reference:                # Tier 3: read-only
  - pyproject.toml
  - src/config.py

signatures:               # Tier 2: extracted interfaces only
  - src/shared_types.py

visible:                  # Tier 1: existence only
  - src/**
  - tests/**

dynamic_deps:             # Known dynamic imports (user-annotated)
  - src/plugins/*.py

# Everything not listed: Tier 0 (blocked)
```

### Permission resolution rules

1. **Explicit > implicit > default.** A file named directly in `working_set` overrides a glob in `visible`.
2. **Least privilege wins.** Conflicting rules resolve to the more restrictive tier.
3. **Monotonic narrowing.** Child agents inherit parent scope as a ceiling -- they can see less, never more.

## Enforcement Layers

### Layer 1: Prompt injection (soft)

Scope instructions are injected into the agent's system prompt. The agent knows it should stay in scope. Zero infrastructure.

### Layer 2: Hook interception (medium)

Claude Code PreToolUse hooks intercept file operations (Read, Edit, Write, Grep, Glob). The hook reads stdin JSON, resolves the target file against the active scope, and allows (exit 0) or denies (JSON to stderr + exit 2).

Denial messages are structured, never silent:

```
[CONTEXT SURGEON: ACCESS DENIED]
File: src/formatter.py
Tier: BLOCKED (Tier 0)
Scope: parser-refactor
Reason: Not in working set or dependency graph.
Action: State which file you need and why. User will decide.
```

### Layer 3: Wrapper proxy (hard, Phase 3+)

Full process-level interception for high-security environments.

**Recommended default:** Layers 1 + 2 combined. Prompt injection makes the agent want to stay in scope. Hooks make it unable to leave.

## Drift Detection

When the scope expands beyond 2x its original size, Context Surgeon warns:

```
[SCOPE DRIFT WARNING]
Original: 4 files (1,850 tokens)
Current:  11 files (5,200 tokens) -- 2.8x expansion
Options: [C]ontinue  [R]eset  [N]ew scope
```

This prevents gradual erosion of the constraint until it becomes meaningless. Track original count via `metadata.original_count` in `.consurg.yaml`.

## Integration with Claude Code Hooks

The plugin registers a PreToolUse hook that intercepts file-access tools:

```json
{
  "PreToolUse": [
    {
      "matcher": "Read|Edit|Write|Grep|Glob",
      "hooks": [
        {
          "type": "command",
          "command": "python ${CLAUDE_PLUGIN_ROOT}/hooks/enforce.py",
          "timeout": 10
        }
      ]
    }
  ]
}
```

The enforcement hook (`hooks/enforce.py`) follows the Git hook convention:
- **Input:** Tool call details via stdin as JSON
- **Allow:** Exit code 0
- **Deny:** JSON with `permissionDecision: "deny"` to stderr, exit code 2

## When NOT to Use

- **Exploratory tasks** -- "understand this codebase" requires broad access
- **Cross-cutting refactors** -- "rename X everywhere" would include everything
- **Bug investigation before localization** -- agent needs to trace freely; scope after finding the bug
- **Small projects** -- if `total_tokens < 10 * working_set_tokens`, overhead exceeds benefit

**The two-phase rule:** Explore unscoped, execute scoped. Never skip Phase 1.

## Slash Commands

| Command | Description |
|---------|-------------|
| `/scope` | Show the active scope with files organized by tier |
| `/scope-status` | Show scope status with tier counts and drift info |
| `/scope-map` | Visualize the file tree with tier annotations |
