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

### `consurg clean [OPTIONS]`

Deactivate the current scope, unwire all tools, and optionally remove `.consurg.yaml`. This is the recommended command for finishing a scoped session.

| Option | Description |
|--------|-------------|
| `--keep-scope` | Skip removing `.consurg.yaml` (leaves scope file in an inactive state) |

Equivalent to running `consurg off`, `consurg wire <tool> --unwire` for all wired tools, and `consurg unpin`.

```bash
consurg clean
consurg clean --keep-scope
```

## Inspection

### `consurg status`

Show current scope status: name, active/inactive, tier counts, and patterns.

### `consurg audit-status`

Show effective audit configuration and current local audit storage usage.

Outputs:
- enabled/disabled state
- storage path
- retention settings (`max_runs`, `max_age_days`, `max_bytes`)
- redaction profile
- current run directory count and byte usage

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

### `consurg map [OPTIONS]`

Visualize every file in the project as a tree with tier badges. Uses `git ls-files` for .gitignore-aware file discovery (falls back to rglob if not in a git repo).

| Option | Description |
|--------|-------------|
| `--depth N` / `-d N` | Maximum directory depth to traverse |
| `--scoped-only` | Only show files with tier >= 1 (hide T0 blocked entries) |

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

### `consurg snap FILES [OPTIONS]`

Render an ad-hoc file selection into a paste-ready prompt in one shot. Unlike `copy`, `snap` does not require or modify `.consurg.yaml` — the selection lives only in the command invocation.

| Argument | Required | Description |
|----------|----------|-------------|
| `FILES` | Yes | Patterns rendered as full content (read-write tier) |

| Option | Description |
|--------|-------------|
| `--read P` | Pattern rendered as full content, read-only tier (repeatable) |
| `--sig P` | Pattern rendered as extracted signatures only (repeatable) |
| `--format` / `-f` | `markdown` (default), `xml`, or `plain` |
| `--task` / `-t` | Task/instructions prepended to the output |
| `--name` / `-n` | Context name shown in the header (default `snapshot`) |
| `--clip` / `-c` | Copy the result to the clipboard |
| `--out` / `-o` | Write the result to a file (e.g. `context.md`) |
| `--max-file-bytes N` | Per-file size limit override for this invocation |
| `--max-total-bytes N` | Total output size limit override for this invocation |

Higher tiers win when patterns overlap. `file_context_ui` limits and `never_include` rules are respected; excluded and oversized files are listed in the `## Omitted` section, and a hint suggests the size-override flags when files were dropped for size. Overrides are still capped by the hard maximums (10 MB per file, 50 MB total).

```bash
consurg snap "src/auth/*.py" --read "src/core/config.py" --sig "src/types.py" --clip
consurg snap "docs/*.md" -t "summarize the docs" -o context.md
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

## pk-agent Scope Workflow

### `consurg scaffold-pk-agents [OPTIONS]`

Scaffold two `pk-agent` agents for scope planning:
- `consurg-scope-selector.pk-agent`
- `consurg-excluded-summarizer.pk-agent`

Also creates `.agents/pk-agents/README.md` with a runbook.

| Option | Description |
|--------|-------------|
| `--force` | Overwrite existing scaffold files |

```bash
consurg scaffold-pk-agents
consurg scaffold-pk-agents --force
```

### `consurg apply-proposal [OPTIONS]`

Map a scope proposal into `.consurg.yaml`.

Expected proposal keys:
- `include_context` -> mapped to `working_set` (T4)
- `read_only` -> mapped to `reference` (T3)
- `exclude` -> remains implicit T0 blocked (not written as a tier list)

| Option | Default | Description |
|--------|---------|-------------|
| `--proposal-file PATH` | `.consurg/recommendations/scope-proposal.yaml` | Path to proposal YAML |
| `--apply` | false | Write mapped values to `.consurg.yaml` (without this, preview only) |

```bash
consurg apply-proposal
consurg apply-proposal --apply
consurg apply-proposal --proposal-file alt/scope-proposal.yaml --apply
```

## Audit Telemetry

Audit persistence is opt-in and disabled by default.

### Environment variables

- `CONSURG_AUDIT_PERSIST=1` -- enable persistent audit traces (default disabled)
- `CONSURG_AUDIT_MAX_RUNS=200`
- `CONSURG_AUDIT_MAX_AGE_DAYS=14`
- `CONSURG_AUDIT_MAX_BYTES=104857600`

### Config file

- `.consurg-audit.yaml` with retention and redaction settings
- Environment variables override file values

When enabled, `consurg wrap` persists redacted traces to `.pk-agent/runs/<timestamp>/trace.json`.

See `docs/pk-agent-audit-integration.md` for full contract, schema, and policy details.

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Error (no scope, invalid input, etc.) |
| _N_ | For `wrap`, the subprocess exit code is propagated |
