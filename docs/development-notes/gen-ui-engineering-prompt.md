# Consurg Gen-UI Agent: Engineering Implementation Prompt

## What you are building

An LLM-powered **context partitioning agent** for Consurg. The user describes a task in natural language ("We're implementing OAuth for the API layer"). The agent analyzes the codebase, identifies which files are relevant, **partitions them into isolated context clusters**, and spawns separate scoped workspaces — each with its own file set and LLM chat interface.

This solves the problem of AI coding agents ingesting irrelevant context in large codebases. Instead of the agent grepping around and polluting its context window, Consurg's agent pre-computes the minimal file set(s) needed for the task.

## Architecture overview

```
User: "Working on Feature X"
         │
         ▼
┌─────────────────────────┐
│  1. ANALYZE              │  Consurg agent receives:
│  - Full file tree        │  - repo file list (git ls-files)
│  - Dependency graph      │  - import/call graph (trace/)
│  - User's task prompt    │  - .consurg.yaml scope config
└────────────┬────────────┘
             ▼
┌─────────────────────────┐
│  2. LLM CALL             │  Single structured LLM call.
│  Input: file tree +      │  Model: provider-agnostic
│    dep graph + task       │  (configured in .consurg.yaml)
│  Output: N file clusters  │
│    with rationale         │
└────────────┬────────────┘
             ▼
┌─────────────────────────┐
│  3. PROPOSE              │  Present clusters to user
│  Cluster 1: auth/        │  in TUI or web UI.
│    [6 files] — "OAuth    │  User can accept, reject,
│     flow + middleware"    │  or manually edit each cluster.
│  Cluster 2: tests/       │
│    [4 files] — "Related  │
│     test coverage"       │
└────────────┬────────────┘
             ▼
┌─────────────────────────┐
│  4. SPAWN                │  Each approved cluster
│  ┌──────┐  ┌──────┐     │  becomes an isolated context:
│  │Ctx 1 │  │Ctx 2 │     │  - Own .consurg.yaml scope
│  │+Chat │  │+Chat │     │  - Own LLM chat interface
│  └──────┘  └──────┘     │  - Wired to downstream tool
└─────────────────────────┘
```

## Existing code you MUST use

Do not reinvent what already exists. The codebase is at `consurg/` and has:

| Module | What it does | How you use it |
|--------|-------------|----------------|
| `scope.py` | `Scope` dataclass, `load_scope()` from YAML | Each cluster becomes a `Scope`. Use this to serialize. |
| `trace/graph.py` | `DependencyGraph` — builds import/call graphs | Feed this to the LLM as structured context for file relationship analysis. |
| `trace/python_resolver.py` | Resolves Python imports to file paths | Use to enrich the dependency graph before LLM call. |
| `trace/ts_resolver.py` | Resolves TS/JS imports to file paths | Same as above for JS/TS projects. |
| `file_context_ui.py` | Web UI file picker + `compose_prompt()` | Extend or replace for the proposal/review step. The `start_ui_server` pattern is reusable. |
| `adapters/` | Generates output for Claude, Cursor, Aider, generic | After clusters are approved, use adapters to produce the final scope artifacts. |
| `wire/` | Wires scope to Claude Code, pk-agent, Codex, Gemini, etc. | After adapters produce artifacts, wire them to the target tool. |
| `enforce.py` | Tier resolution with pattern matching | Enforce that LLM-selected files respect existing tier constraints. |
| `guard/` | State management, lockfile, TUI | Use guard patterns for the agent session lifecycle. |
| `audit.py` | Trace persistence | Audit the LLM's file selection decisions for traceability. |
| `cli.py` | Typer CLI app | Add the new command here: `consurg agent` or `consurg plan`. |

## LLM integration design

### Provider-agnostic

The agent must not hardcode a provider. Use a config block in `.consurg.yaml`:

```yaml
agent:
  provider: anthropic          # or openai, gemini, ollama
  model: claude-sonnet-4-5-20250929  # or gpt-4o, gemini-2.5-pro, etc.
  api_key_env: ANTHROPIC_API_KEY     # env var name holding the key
  max_tokens: 4096
  temperature: 0.0                   # deterministic file selection
```

Implement a thin provider abstraction — do NOT pull in a heavy framework (no LangChain, no CrewAI). Use the provider's native Python SDK directly:
- `anthropic` for Anthropic
- `openai` for OpenAI
- `google-genai` for Gemini

Keep it to a single `call_llm(messages, schema) -> dict` function with provider dispatch. The LLM is called exactly **once** per agent invocation (not a multi-turn agent loop).

### Structured output contract

The LLM receives a system prompt + user message and returns a **single JSON payload** conforming to this schema:

```json
{
  "clusters": [
    {
      "id": "auth-flow",
      "label": "OAuth authentication flow",
      "rationale": "These files implement the OAuth handshake, token storage, and middleware validation.",
      "files": [
        "src/auth/oauth.py",
        "src/auth/tokens.py",
        "src/middleware/auth_check.py",
        "src/config/auth_settings.py"
      ],
      "confidence": 0.92,
      "dependencies_traced": true
    },
    {
      "id": "auth-tests",
      "label": "Auth test coverage",
      "rationale": "Test files that directly exercise the auth flow and would break if auth changes.",
      "files": [
        "tests/test_oauth.py",
        "tests/test_auth_middleware.py"
      ],
      "confidence": 0.87,
      "dependencies_traced": true
    }
  ],
  "excluded_rationale": "Excluded 847 files unrelated to OAuth. Notable exclusions: src/billing/ (no auth dependency), src/ui/ (no direct auth imports).",
  "warnings": []
}
```

**Enforce this with JSON Schema validation on the response.** If the LLM returns malformed output, fail loudly — do not silently degrade.

### System prompt for the file-selection LLM

The system prompt must include:
1. The complete file tree (from `git ls-files`, filtered by `.consurg.yaml` deny patterns)
2. The dependency graph edges (from `trace/graph.py`) — as a compact adjacency list, not a full matrix
3. The user's task description
4. Instructions to return the JSON schema above and nothing else
5. Explicit constraint: **only select files that exist in the provided file tree**

Keep the system prompt token-efficient. The file tree for a 1000-file repo should compress to ~5K tokens using path prefixes. The dep graph edges add ~2-5K tokens. Budget 1-2K for instructions. Total: ~10K input tokens for a large repo.

### Token budget strategy

For repos exceeding ~2000 files:
1. First pass: send only directory structure (not individual files) + task description
2. LLM returns candidate directories
3. Second pass: send full file list for only those directories + dep graph edges within them
4. LLM returns final clusters

This keeps the agent usable on monorepos without blowing the context window.

## State management

Use a simple linear state machine — **not** a full statechart library. The agent flow is synchronous and single-user:

```
idle → analyzing → proposing → reviewing → spawning → done
                                  │
                                  └→ rejected → analyzing (user edits + re-runs)
```

Implement this as an enum + transition function in Python. Do not pull in XState or any external FSM library. The states map to:

| State | What happens |
|-------|-------------|
| `idle` | No agent session active |
| `analyzing` | Building file tree + dep graph |
| `proposing` | LLM call in progress |
| `reviewing` | User sees proposed clusters, can accept/edit/reject |
| `spawning` | Writing scope files + wiring to downstream tools |
| `done` | Contexts are live |
| `rejected` | User rejected proposal; can re-prompt or edit manually |

Persist state to `.consurg-agent-state.json` so the session survives if the user closes the terminal. The guard module's lockfile pattern is a reference for this.

## UI/CLI parity principle

**CRITICAL CONSTRAINT**: The web UI and the CLI must have full functional parity for all non-generative operations. A user who prefers the browser must be able to do everything a CLI user can, and vice versa. The only CLI-exclusive feature is the LLM-powered `consurg plan` command (the generative file selection). Everything else — scope management, file browsing, cluster review/edit, wiring, spawning contexts — works identically in both interfaces.

This means: **build the logic layer first, then attach two presentation layers to it.**

### Shared service layer

Every user-facing operation must be implemented as a function in the service layer, NOT in the CLI handler or the HTTP handler. Both interfaces call the same functions:

```
┌──────────────┐     ┌──────────────┐
│   CLI (Typer  │     │  Web UI      │
│   + Rich)    │     │  (HTTP API)  │
└──────┬───────┘     └──────┬───────┘
       │                    │
       ▼                    ▼
┌─────────────────────────────────────┐
│         Service Layer               │
│  (agent/, scope.py, wire/, etc.)    │
│                                     │
│  list_files(cwd, config) → [...]    │
│  propose_clusters(task) → [...]     │  ← LLM call (CLI-triggered only)
│  get_clusters() → [...]             │
│  edit_cluster(id, files) → Cluster  │
│  accept_clusters(ids) → [Scope]     │
│  spawn_contexts(scopes, target)     │
│  get_scopes() → [Scope]            │
│  wire_scope(scope, target) → path   │
│  get_agent_state() → State          │
└─────────────────────────────────────┘
```

The web UI is an HTTP API (extending `file_context_ui.py`'s server pattern) that exposes these service functions as REST endpoints. The CLI calls them directly as Python functions.

### Operations that MUST work in both interfaces

| Operation | CLI command | Web API endpoint |
|-----------|------------|-----------------|
| List repo files | `consurg ls` | `GET /api/files` |
| View current scope(s) | `consurg show` | `GET /api/scopes` |
| Create/edit scope manually | `consurg add <files>` | `POST /api/scopes` |
| Remove files from scope | `consurg rm <files>` | `DELETE /api/scopes/{id}/files` |
| View proposed clusters | `consurg plan --show` | `GET /api/clusters` |
| Edit a cluster (add/remove files) | `consurg plan --edit <id>` | `PATCH /api/clusters/{id}` |
| Accept clusters | `consurg plan --accept` | `POST /api/clusters/accept` |
| Reject / re-prompt | `consurg plan --reject` | `POST /api/clusters/reject` |
| Spawn isolated contexts | `consurg spawn` | `POST /api/spawn` |
| Wire scope to tool | `consurg wire <target>` | `POST /api/wire` |
| View agent state | `consurg status` | `GET /api/status` |
| Audit trail | `consurg audit` | `GET /api/audit` |
| View dependency graph | `consurg trace <file>` | `GET /api/trace/{file}` |

### CLI-only (generative)

| Operation | CLI command | Why CLI-only |
|-----------|------------|-------------|
| Run LLM analysis | `consurg plan "task"` | Requires LLM API key + is a one-shot call; results are then available in both interfaces |

The LLM call happens via CLI. Once clusters are proposed, they're persisted to `.consurg-agent-state.json`. At that point the web UI can read and display them. The web UI user can then review, edit, accept/reject — all the same operations as CLI.

### Web UI design

Extend `file_context_ui.py`'s `start_ui_server` pattern into a full application server. The existing vanilla HTML + `fetch()` approach stays — no React, no build step.

**Views the web UI must support:**

1. **Dashboard** — Current agent state, active scopes, recent audit entries
2. **File browser** — Full repo tree with deny-pattern highlighting (extends existing file picker)
3. **Cluster review** — Card layout showing each proposed cluster with file lists, rationale, confidence scores. Drag-and-drop file reassignment between clusters. Accept/reject/edit buttons per cluster.
4. **Scope manager** — View, create, edit, delete scopes manually. Same functionality as `consurg add/rm/show`.
5. **Spawn panel** — Select approved clusters, pick target tool, spawn isolated contexts
6. **Trace viewer** — Visual dependency graph for a selected file (optional v1.1)

### TUI design

Use Rich (already a dependency) for all CLI output. For the cluster review step specifically:

```
┌─────────────────────────────────────────────────┐
│ Consurg Agent — Proposed Contexts               │
├──────────────┬──────────┬───────────────────────┤
│ Cluster      │ Files    │ Rationale             │
├──────────────┼──────────┼───────────────────────┤
│ auth-flow    │ 4 files  │ OAuth handshake +     │
│   (0.92)     │          │ middleware             │
│ auth-tests   │ 2 files  │ Test coverage for     │
│   (0.87)     │          │ auth flow              │
├──────────────┴──────────┴───────────────────────┤
│ [a]ccept  [e]dit  [r]eject  [d]etail  [w]eb     │
└─────────────────────────────────────────────────┘
```

`[w]eb` opens the web UI at the cluster review view — seamless handoff between interfaces.
`[d]etail` expands a cluster to show all file paths.
`[e]dit` lets the user add/remove files from a cluster.
`[a]ccept` proceeds to spawn.
`[r]eject` lets the user re-describe the task.

## Spawning isolated contexts

When the user accepts clusters, for each cluster:

1. Create a temporary `.consurg.yaml` scoped to that cluster's files
2. Run the appropriate adapter (`adapters/`) to generate the scope artifact
3. Run the appropriate wire (`wire/`) to install the scope into the target tool
4. If the target tool supports it, launch a new session/window (e.g., `claude --scope .consurg-ctx-1.yaml`)

The "LLM chatbox" in each context is **the downstream tool itself** (Claude Code, Cursor, Aider). Consurg does not build its own chat — it scopes the existing tool.

## File structure for new code

```
consurg/
├── agent/
│   ├── __init__.py
│   ├── analyzer.py        # Builds file tree + dep graph payload for LLM
│   ├── llm.py             # Provider-agnostic LLM caller
│   ├── proposer.py        # Formats LLM response into Cluster objects
│   ├── spawner.py         # Writes scope files + wires to tools
│   ├── state.py           # State machine (enum + transitions + persistence)
│   └── schema.py          # JSON Schema + validation for LLM output
│
├── service/
│   ├── __init__.py
│   ├── files.py           # list_files, get_file_tree, is_denied (shared logic)
│   ├── clusters.py        # get/edit/accept/reject clusters (reads agent state)
│   ├── scopes.py          # create/read/update/delete scopes
│   ├── wiring.py          # wire scope to target tool
│   ├── spawning.py        # spawn isolated contexts from accepted clusters
│   ├── tracing.py         # dep graph queries
│   └── auditing.py        # read audit trail
│
├── server/
│   ├── __init__.py
│   ├── app.py             # HTTP server (extends file_context_ui.py pattern)
│   ├── routes.py          # REST endpoint handlers → call service layer
│   └── html.py            # HTML templates (vanilla, no framework)
│
├── tui/
│   ├── __init__.py
│   └── review.py          # Rich-based cluster review + interactive edit
│
├── ...existing modules unchanged...
```

The key principle: `agent/` does the LLM-powered analysis. `service/` exposes all operations as plain functions. `server/` and `tui/` are presentation layers that call `service/`. Neither `server/` nor `tui/` contains business logic.

Migrate existing logic from `file_context_ui.py` into `service/files.py` and `server/`. The old module becomes a thin compatibility shim that imports from the new locations.

Add to `cli.py`:

```python
@app.command()
def plan(
    task: Annotated[str, typer.Argument(help="Describe the feature/task")],
    provider: Annotated[str, typer.Option(help="LLM provider")] = None,
    model: Annotated[str, typer.Option(help="Model name")] = None,
    target: Annotated[str, typer.Option(help="Target tool: claude, cursor, aider, generic")] = "claude",
    web: Annotated[bool, typer.Option(help="Open web UI instead of TUI")] = False,
):
    """Analyze codebase and propose isolated contexts for a task."""

@app.command()
def ui(
    port: Annotated[int, typer.Option(help="Port for web UI")] = 0,
):
    """Launch the Consurg web UI (full-featured, non-generative)."""
    # Starts the server/ app with all views: dashboard, file browser,
    # scope manager, cluster review, spawn panel
```

## Research-backed design decisions

These come from extensive analysis of generative UI literature (see `docs/development-notes/gen-ui-briefing.md`):

1. **Tool-calling + schema validation over code generation.** The LLM returns structured JSON, never raw code. This gives 0% output error rate on modern models (Gemini 3 benchmark) vs 60% on code-gen approaches. Validate with JSON Schema on every response.

2. **Task-Driven Data Model pattern.** Consurg's agent outputs a structured data model (clusters with file lists, rationale, confidence scores) — not UI components. Downstream consumers (TUI, web UI, adapters) render from the model. This is the Jelly/UCSD architecture, confirmed as optimal for CLI tools that produce payloads.

3. **Single LLM call, not an agent loop.** Multi-turn agent loops are fragile and expensive. The file-selection task is well-scoped enough for a single structured call. If the user rejects, they re-prompt — this is cheaper and more controllable than autonomous retry loops.

4. **Post-processing over prevention.** If the LLM includes a file not in the tree, strip it and add a warning. Don't re-call the LLM. Post-processing catches 95%+ of edge cases at near-zero cost.

5. **Confidence scores for transparency.** The LLM must report how confident it is per cluster. Clusters below 0.7 confidence get a visual warning in the review UI. This lets the user focus their attention.

## What NOT to build

- **No autonomous multi-turn agent loop.** One LLM call per invocation.
- **No built-in chat interface.** The chat is the downstream tool (Claude Code, Cursor). Consurg scopes it, not replaces it.
- **No real-time streaming UI.** The LLM call returns a complete JSON payload. No streaming partial clusters.
- **No XState or external FSM library.** A Python enum with a transition dict is sufficient.
- **No LangChain, CrewAI, or agent framework.** Direct SDK calls only.
- **No new frontend framework.** The web UI (if built) uses the existing vanilla HTML + fetch pattern from `file_context_ui.py`.

## Acceptance criteria

### Agent (generative, CLI-only)
1. `consurg plan "Implement OAuth for API layer"` produces proposed clusters in TUI
2. The agent works with at least 2 LLM providers (Anthropic + OpenAI)
3. File selection respects existing `.consurg.yaml` deny patterns and tier enforcement
4. Dependency tracing (`trace/`) is used to ensure clusters include transitively-required files
5. LLM output is validated against JSON Schema; malformed responses fail with a clear error
6. Agent decisions are auditable via `audit.py`
7. Works on repos up to 5000 files without exceeding 32K input tokens

### Parity (both CLI and web UI)
8. User can view proposed clusters with file lists, rationale, and confidence scores
9. User can accept, edit (add/remove files), or reject clusters
10. User can manually create/edit/delete scopes without the agent
11. Accepted clusters create isolated `.consurg.yaml` scopes
12. Scopes are wired to the target tool via existing `wire/` module
13. User can view the dependency graph for any file
14. User can browse all repo files with deny-pattern highlighting
15. User can view agent state and audit trail
16. `consurg ui` launches web UI; all operations listed in the parity table work via REST endpoints
17. `[w]eb` from TUI review opens the web UI at the same state — seamless handoff

### Architecture
18. All business logic lives in `service/` — no logic in CLI handlers or HTTP handlers
19. `file_context_ui.py` functionality is preserved (migrated into `service/` + `server/`)
20. Adding a new operation requires: one service function + one CLI command + one REST route (no logic duplication)

## Open design decisions (document your choice)

These were not resolved during research. Pick one, document why, and implement it:

1. **Review UI default**: TUI-first with `--web` flag, or web-first with `--tui` flag?
2. **Cluster granularity**: Should the LLM default to few large clusters or many small ones? (Recommend: bias toward 2-4 clusters with `max_clusters` config)
3. **Dependency depth**: How many hops of transitive imports to include? (Recommend: 2 hops default, configurable)
4. **Re-analysis on edit**: If the user manually adds a file to a cluster, should the agent re-analyze to pull in that file's dependencies? (Recommend: yes, but only for the edited cluster)
