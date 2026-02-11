# CLI Reference

All commands are invoked via `consurg` (or `python -m consurg`).

## Scope Management

### `consurg init [NAME]`

Create `.consurg.yaml` in the current directory.

| Argument | Default | Description |
|----------|---------|-------------|
| `NAME` | Current directory name | Scope name |

### `consurg add FILES [OPTIONS]`

Add file patterns to a tier.

| Argument | Required | Description |
|----------|----------|-------------|
| `FILES` | Yes | One or more file patterns (shell wildcards) |

| Option | Default | Description |
|--------|---------|-------------|
| `--read` | false | Add to `reference` (T3) instead of `working_set` (T4) |
| `--sig` | false | Add to `signatures` (T2) instead of `working_set` (T4) |

Duplicate patterns are silently ignored. Drift warnings trigger when patterns exceed 2x original count.

**Note:** There is no `--vis` flag for T1 (visible). To add files to T1, edit `.consurg.yaml` directly.

### `consurg remove FILES`

Remove patterns from all tier lists. Warns if a pattern is not found.

### `consurg on`

Activate enforcement. Sets `active: true` in `.consurg.yaml`.

### `consurg off`

Deactivate enforcement. Sets `active: false`. All access allowed.

### `consurg pin`

Persist the current scope (defers to `consurg init` for creation).

### `consurg unpin`

Delete `.consurg.yaml` from the project root.

## Inspection

### `consurg status`

Display scope name, active/inactive state, tier counts, and patterns.

```
         Scope: auth-refactor (ACTIVE)
+--------------+-------+--------------------+
| Tier         | Count | Patterns           |
+--------------+-------+--------------------+
| 4 READ-WRITE |     2 | src/auth/*.py, ... |
| 3 READ-ONLY  |     1 | src/core/*.py      |
| 2 SIGNATURE  |     0 | -                  |
| 1 EXISTENCE  |     0 | -                  |
+--------------+-------+--------------------+
```

### `consurg map`

Visualize every file as a tree with tier badges. Excludes `.git`, `__pycache__`, `.pytest_cache`.

```
auth-refactor
[RW] #### src/auth/login.py
[RO] ### src/core/database.py
[SIG] ## types/auth.pyi
[--] -- README.md
```

## Scope Generation

### `consurg trace ENTRY_FILES [OPTIONS]`

Trace import dependencies and classify into tiers.

| Argument | Required | Description |
|----------|----------|-------------|
| `ENTRY_FILES` | Yes | One or more entry point files |

| Option | Default | Description |
|--------|---------|-------------|
| `--depth N` | 3 | Maximum trace depth |
| `--apply` | false | Write results to `.consurg.yaml` |

Supports Python (AST-based) and TypeScript/JavaScript (regex-based with tsconfig support).

### `consurg git-diff [BASE] [OPTIONS]`

Build scope from files changed relative to a base branch.

| Argument | Default | Description |
|----------|---------|-------------|
| `BASE` | Auto-detect (`main` or `master`) | Base branch |

| Option | Default | Description |
|--------|---------|-------------|
| `--apply` | false | Write results to `.consurg.yaml` |

## Export

### `consurg export --format FORMAT`

Export scope in a tool-specific format to stdout.

| Format | Output |
|--------|--------|
| `claude` | Markdown for system prompt injection |
| `cursor` | Cursor rules (`allow:`, `read-only:`, `signature:`, `visible:`) |
| `aider` | CLI args (`--file`, `--read`) |
| `generic` | Plain-text `[SCOPE]` block |

## Guard

### `consurg guard [OPTIONS]`

Start the interactive scope firewall.

| Option | Default | Description |
|--------|---------|-------------|
| `-i` / `--no-i` | `-i` | Interactive TUI mode |
| `--port N` | 9876 | HTTP server port |
| `--no-tui` | false | Headless mode (no dashboard) |

Press `Q` to quit. Approval keys: `W` (T4), `R` (T3), `S` (T2), `D` (deny).

## Wire

### `consurg wire TOOL [OPTIONS]`

Auto-configure hooks for a supported AI tool.

| Argument | Values |
|----------|--------|
| `TOOL` | `claude`, `pk-agent`, `droid`, `gemini`, `codex` |

| Option | Description |
|--------|-------------|
| `--unwire` | Remove hooks instead of installing |

Status output: `wired`, `not wired`, or `partial`.

## Wrap

### `consurg wrap -- COMMAND [ARGS]`

Run a command with embedded headless guard. Sets `CONSURG_GUARD_PORT` and `CONSURG_ACTIVE=1` in subprocess environment. Exit code propagated from wrapped command.

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Error (no scope, invalid input, etc.) |
| _N_ | For `wrap`, subprocess exit code propagated |
