# CLI Reference

All commands are invoked via `consurg` (or `python -m consurg`).

## Scope Management

### `consurg init [NAME]`

Create a new `.consurg.yaml` scope file in the current directory.

| Argument | Default | Description |
|----------|---------|-------------|
| `NAME` | Current directory name | Scope name |

```bash
consurg init auth-refactor
```

### `consurg add FILES [OPTIONS]`

Add file patterns to a tier list.

| Argument | Required | Description |
|----------|----------|-------------|
| `FILES` | Yes | One or more file patterns (shell wildcards) |

| Option | Description |
|--------|-------------|
| `--read` | Add to `reference` (T3 read-only) instead of `working_set` |
| `--sig` | Add to `signatures` (T2 signature-only) instead of `working_set` |

Default tier is `working_set` (T4 read-write).

```bash
consurg add "src/auth/*.py"              # T4
consurg add --read "src/core/*.py"       # T3
consurg add --sig "types/*.pyi"          # T2
```

Duplicate patterns are silently ignored. Drift warnings are displayed when the scope exceeds 2x the original file count.

### `consurg remove FILES`

Remove file patterns from all tier lists.

```bash
consurg remove "src/auth/*.py"
```

Warns if a pattern is not found in any tier.

### `consurg on`

Activate the current scope. Enforcement begins.

### `consurg off`

Deactivate the current scope. Enforcement stops, all access is allowed.

### `consurg pin`

Pin the current scope. Currently defers to `consurg init` for creation.

### `consurg unpin`

Remove `.consurg.yaml` from the project root.

## Inspection

### `consurg status`

Show current scope status: name, active/inactive, tier counts, and patterns.

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

Visualize every file in the project as a tree with tier badges.

```
auth-refactor
[RW] #### src/auth/login.py
[RO] ### src/core/database.py
[--] -- README.md
```

Excluded directories: `.git`, `__pycache__`, `.pytest_cache`.

## Scope Generation

### `consurg trace ENTRY_FILES [OPTIONS]`

Trace import dependencies from entry files and classify into tiers.

| Argument | Required | Description |
|----------|----------|-------------|
| `ENTRY_FILES` | Yes | One or more entry point files |

| Option | Default | Description |
|--------|---------|-------------|
| `--depth N` | 3 | Maximum trace depth |
| `--apply` | false | Write results to `.consurg.yaml` |

Supports Python and TypeScript/JavaScript.

```bash
consurg trace src/auth/login.py --depth 2 --apply
```

### `consurg git-diff [BASE] [OPTIONS]`

Build scope from files changed relative to a base branch.

| Argument | Default | Description |
|----------|---------|-------------|
| `BASE` | Auto-detect (`main` or `master`) | Base branch |

| Option | Default | Description |
|--------|---------|-------------|
| `--apply` | false | Write results to `.consurg.yaml` |

```bash
consurg git-diff main --apply
```

## Export

### `consurg export --format FORMAT`

Export scope in a tool-specific format.

| Option | Required | Values |
|--------|----------|--------|
| `--format` | Yes | `claude`, `cursor`, `aider`, `generic` |

```bash
consurg export --format claude
consurg export --format aider
```

Output is printed to stdout. Pipe or redirect as needed.

## Guard

### `consurg guard [OPTIONS]`

Start the interactive scope firewall.

| Option | Default | Description |
|--------|---------|-------------|
| `-i` / `--no-i` | `-i` (interactive) | Enable/disable interactive TUI mode |
| `--port N` | 9876 | HTTP server port |
| `--no-tui` | false | Run headless (no TUI dashboard) |

```bash
consurg guard -i                    # Interactive TUI
consurg guard --no-tui              # Headless
consurg guard -i --port 8888        # Custom port
```

Press `Q` to quit. See [guard.md](guard.md) for full TUI documentation.

## Wire

### `consurg wire TOOL [OPTIONS]`

Auto-configure hooks for a supported AI tool.

| Argument | Required | Values |
|----------|----------|--------|
| `TOOL` | Yes | `claude`, `pk-agent`, `droid`, `gemini`, `codex` |

| Option | Description |
|--------|-------------|
| `--unwire` | Remove hooks instead of installing |

```bash
consurg wire claude                 # Install hooks
consurg wire claude --unwire        # Remove hooks
```

## Wrap

### `consurg wrap -- COMMAND [ARGS]`

Run a command with embedded headless scope enforcement.

Everything after `--` is the command to execute. The command runs with `CONSURG_GUARD_PORT` and `CONSURG_ACTIVE=1` set in its environment.

```bash
consurg wrap -- claude "fix the login bug"
consurg wrap -- python my_script.py
```

The wrapped command's exit code is propagated. The guard starts on a random port and cleans up automatically.

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Error (no scope, invalid input, etc.) |
| _N_ | For `wrap`, the subprocess exit code is propagated |
