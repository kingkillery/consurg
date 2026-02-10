# Context Surgeon - Product Requirements Document

**Version:** 0.1.0
**Status:** Draft
**Author:** Preston Nackos
**Date:** 2026-02-10

---

## 1. Product Overview

### 1.1 One-Liner

Context Surgeon is a Python library and CLI that temporarily restricts AI coding agents to a declared subset of files, improving reasoning accuracy by eliminating context noise.

### 1.2 The Problem

AI coding agents (Claude Code, Cursor, Aider) have unrestricted codebase access. During focused work on 3-5 files, agents routinely read 12-20 files, burning context window on irrelevant code. This causes:

- **Accuracy degradation**: 15-25% more mistakes when the relevant signal ratio drops below 0.4
- **Wasted compute**: ~47,000 tokens/session spent on files that don't matter
- **Subagent drift**: spawned agents explore freely, compounding the noise
- **Unintended edits**: agents suggest changes to files you didn't ask about

### 1.3 The Solution

Declare a **scope** - a temporary boundary around the files that matter. The agent operates inside the boundary. Everything outside is invisible, read-only, or reduced to type signatures. Scopes are ephemeral (die with the session), tiered (five levels of access, not just yes/no), and enforced (prompt instructions backed by tool-call interception).

### 1.4 Positioning

| Tool | Direction | What it does |
|------|-----------|--------------|
| x16 / repoprompt | Additive | Builds context *from* the repo into a prompt |
| .claudeignore | Permanent exclusion | Blocks infrastructure noise (node_modules, build/) |
| **Context Surgeon** | **Subtractive, temporary** | **Restricts context *to* a working set for the current task** |

Complementary to all of the above. The workflow: explore broadly (unscoped) to understand the task, then execute precisely (scoped) to do the work.

### 1.5 Prior Art

| Tool / Pattern | Relationship to Context Surgeon |
|---------------|--------------------------------|
| **Aider** `--file` / `--read` | Tier 3 and 4 are Aider's model. We add Tiers 0-2 and portability. |
| **pre-commit** framework | Same YAML + stdin/exit-code hook convention. |
| **Git hooks** | Same I/O contract (stdin JSON, exit code signaling). |
| **SWE-agent** sandbox | Same principle (restrict agent), different axis (commands vs files). |
| **OpenHands** container isolation | Our Layer 3 is a lighter-weight version. |
| **`.d.ts` / `.pyi` stubs** | Direct inspiration for Tier 2 (signature-only access). |
| **Capability-based security** | Monotonic narrowing, structured denial on violation. |

Gap in existing tools: none combine tiered access (5 levels) + dependency-aware scoping (auto-classify imports) + portable format (works across agent frameworks).

---

## 2. Core Concepts

### 2.1 Scope

A scope is a named, temporary, session-level declaration of:
- Which files the agent can interact with
- What level of access each file gets
- Why the restriction exists (human-readable reason)

Scopes are ephemeral by default. New session = full access. Optional `pin` for multi-day persistence.

### 2.2 The Five-Tier Permission Model

| Tier | Label | Agent sees | Token cost | Use case |
|------|-------|-----------|------------|----------|
| 0 | **Blocked** | Nothing. File doesn't exist. | 0 | Unrelated modules, secrets, `.env` |
| 1 | **Existence** | Filename in directory listings. No content. | ~5/file | Project structure awareness |
| 2 | **Signature** | Type definitions, function headers, class interfaces. No implementation. | ~50-150/file | Shared types, API contracts, interfaces |
| 3 | **Read-only** | Full file content. Cannot modify. | Full | Config, manifests, test fixtures |
| 4 | **Read-write** | Full access. | Full | The working set (files being edited) |

**Tier 2 is the key innovation.** It's context compression that preserves semantic information. The agent gets enough to reason about types and contracts without implementation noise. Same principle as `.d.ts` (TypeScript) or `.pyi` (Python) stub files.

### 2.3 Permission Composition

Three resolution rules when tiers conflict:

1. **Explicit > implicit > default.** A file named in `working_set` overrides a glob in `visible`.
2. **Least privilege wins.** Conflicting rules resolve to the more restrictive tier.
3. **Monotonic narrowing.** Child agents inherit parent scope as a ceiling - they can see less, never more.

---

## 3. Scope Schema

### 3.1 File Format

```yaml
# .consurg.yaml
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
  - src/tokenizer.py

signatures:               # Tier 2: extracted interfaces only
  - src/shared_types.py
  - src/interfaces/*.py

visible:                  # Tier 1: existence only
  - src/**
  - tests/**

dynamic_deps:             # Known dynamic imports (user-annotated)
  - src/plugins/*.py

# Everything not listed: Tier 0 (blocked)
```

### 3.2 Portable JSON Format

For tool adapters and programmatic use:

```json
{
  "$schema": "https://consurg.dev/scope/v1.json",
  "version": 1,
  "scope_name": "parser-refactor",
  "active": true,
  "created": "2026-02-10T14:30:00Z",
  "reason": "Refactoring parser pipeline",
  "tiers": {
    "read_write": ["src/parser.py", "src/parser_helpers/*.py"],
    "read_full": ["pyproject.toml", "src/config.py", "src/tokenizer.py"],
    "read_signature": ["src/shared_types.py"],
    "existence_only": ["src/**", "tests/**"],
    "blocked_patterns": ["**/.env", "**/secrets/**"]
  },
  "extracted_signatures": {
    "src/shared_types.py": "class ASTNode:\n    kind: str\n    children: list['ASTNode']\n    span: tuple[int, int]\n"
  },
  "trace_config": {
    "depth": 1,
    "language": "python",
    "auto_promote_types": true
  }
}
```

---

## 4. Scope Declaration Methods

### 4.1 Explicit File List

```bash
consurg add src/parser.py src/helpers/*.py
```

User names files directly. Maximum control.

### 4.2 Dependency Trace

```bash
consurg trace src/parser.py --depth 1
```

Resolves import graph from an entry point. Classifies each dependency by tier:
- `if TYPE_CHECKING:` imports -> Tier 2 (signature)
- Value imports -> Tier 3 (read-only)
- Side-effect imports -> Tier 1 (existence)
- Dynamic/unresolvable imports -> flagged for user decision

Presents a recommendation the user can accept, edit, or reject.

**Depth heuristics:**
- Depth 1 captures 85-90% of needed context. Default.
- If depth-1 produces >15 files, demote value-imports to signature-only unless directly called.
- Depth 2+ only on explicit request.

### 4.3 Git-Aware

```bash
consurg git-diff            # uncommitted changes
consurg git-diff HEAD~3     # last 3 commits
```

Scope to files touched in recent work.

### 4.4 Interactive / Conversational

```
User: "I'm refactoring the parser pipeline. Scope me."
Agent: [runs trace engine, presents recommendation, user approves]
```

---

## 5. The Trace Engine

### 5.1 Purpose

Automatically discover dependencies of working-set files and classify them by tier. This is the differentiator - anyone can build a file allowlist; automatic tier-classified dependency resolution is the hard part.

### 5.2 Architecture

```
┌──────────────────────────┐
│       Trace Engine        │
│  (language-agnostic       │
│   graph builder)          │
└────────────┬─────────────┘
             │
    ┌────────┼────────┬──────────┐
    │        │        │          │
┌───▼──┐ ┌──▼───┐ ┌──▼──┐ ┌───▼───┐
│Python│ │TS/JS │ │ Go  │ │ Rust  │
└──────┘ └──────┘ └─────┘ └───────┘
```

### 5.3 Output: Typed Dependency Graph

```
DependencyGraph:
  nodes: Set[FilePath]
  edges: Set[(source, target, DependencyKind)]

DependencyKind:
  TypeOnly     -> Tier 2 (signature)
  ValueImport  -> Tier 3 (read-only)
  SideEffect   -> Tier 1 (existence)
  Dynamic      -> flag for user
```

### 5.4 Language-Specific Resolvers

**Python:**
- Standard imports (`import foo`, `from foo import bar`) -> resolve via sys.path
- `TYPE_CHECKING` guarded imports -> auto-Tier 2
- Relative imports -> resolve from package root
- Dynamic (`importlib.import_module`) -> flag

**TypeScript/JavaScript:**
- Named imports -> resolve through tsconfig paths, package.json exports
- `import type` -> auto-Tier 2
- Barrel files (`index.ts`) -> trace through to specific source file, not the barrel
- Dynamic (`require(variable)`) -> flag

**Go:**
- Package imports -> map to directory
- Standard library -> ignore (no project context cost)

**Rust:**
- `use crate::` -> resolve to source files
- Standard library -> ignore

### 5.5 Signature Extraction

For Tier 2 files, extract:
- Class/struct definitions with field types
- Function/method signatures (name, params, return type)
- Type aliases, enums, constants
- Exported interfaces

Strip: function bodies, private methods, comments, docstrings (beyond the first line).

The extraction must be language-aware. Phase 1 can use regex heuristics. Phase 3 should use proper AST parsing (tree-sitter recommended for multi-language support).

---

## 6. Enforcement

### 6.1 Layer 1: Prompt Injection (soft)

Inject scope instructions into the agent's system prompt or CLAUDE.md. Zero infrastructure.

```markdown
## Active Scope (Context Surgeon)
WRITE ACCESS: src/parser.py, src/parser_helpers/{a,b,c}.py
READ-ONLY: src/config.py, src/tokenizer.py
SIGNATURE ONLY: src/shared_types.py (signatures below)
ALL OTHER FILES: BLOCKED.
If you need an unlisted file, state which file and why.

### Signatures:
class ASTNode:
    kind: str
    children: list['ASTNode']
    span: tuple[int, int]
```

### 6.2 Layer 2: Hook Interception (medium)

Claude Code PreToolUse hook intercepts file operations. Follows the stdin/exit-code convention used by Git hooks and the [pre-commit](https://pre-commit.com/) framework.

**Hook configuration** (plugin `hooks/hooks.json` or `.claude/settings.json`):

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

**I/O contract** (matches Claude Code hook API):
- **Input:** Tool call details delivered via **stdin as JSON** (`tool_name`, `tool_input` with file path, `cwd`, etc.)
- **Allow:** Exit code 0, no output required.
- **Deny:** JSON with `{"hookSpecificOutput": {"permissionDecision": "deny"}, "systemMessage": "..."}` written to **stderr**, exit code **2**.

The enforce script (see `hooks/enforce.py` in concept doc) reads stdin, resolves the target file path against the active `.consurg.yaml`, determines the tier, and allows or denies accordingly:
- Tier 0-1: deny all operations
- Tier 2-3: deny writes, allow reads
- Tier 4: allow all

**Denial message format:**

```
[CONTEXT SURGEON: ACCESS DENIED]
File: src/formatter.py
Tier: BLOCKED (Tier 0)
Scope: parser-refactor
Reason: Not in working set or dependency graph.
Action: State which file you need and why. User will decide.
```

**Tier 2 limitation at hook layer:** Hooks can allow or deny but cannot transform Read output. A Tier 2 file is either fully readable or blocked - the hook can't strip implementation bodies. Mitigation: pre-extract signatures into the Layer 1 prompt block (Phase 2), or use a Layer 3 proxy for content transformation (Phase 3+).

**Critical design choice:** Structured denial, never silence. Silence causes the agent to hallucinate file contents. An explicit denial with a recovery path prevents hallucination. This follows capability-based security conventions where denied capabilities return structured errors.

### 6.3 Layer 3: Wrapper Proxy (hard)

Full process-level interception. All file I/O routes through a scope-aware proxy. For high-security environments.

```
Agent -> Tool Call -> Scope Proxy -> [in scope?] -> Filesystem
                                  -> [out of scope?] -> Structured Denial
```

### 6.4 Recommended Default

**Layers 1 + 2 combined.** Prompt injection makes the agent *want* to stay in scope. Hooks make it *unable* to leave.

---

## 7. Scope Lifecycle

### 7.1 State Machine

```
[No scope] -> consurg on  -> [Active]  -> consurg off -> [No scope]
                                  |
                                  |-- consurg add <file>     (expand)
                                  |-- consurg remove <file>  (narrow)
                                  |-- consurg status         (inspect)
                                  |-- consurg map            (visualize)
                                  |-- consurg pin            (persist to file)
                                  '-- consurg unpin          (remove persisted)
```

### 7.2 Ephemeral by Default

- Scope lives in memory / temp file during session
- New session = full access (clean slate)
- `consurg pin` writes `.consurg.yaml` for multi-day persistence
- `consurg unpin` removes it

### 7.3 Mid-Session Expansion

When the agent hits a boundary:

```
┌─ SCOPE BOUNDARY ──────────────────────────────────┐
│ tests/test_parser.py is outside current scope      │
│                                                    │
│ [S] Signature only   [R] Read-only   [W] Write    │
│ [D] Deny             [A] Auto-approve similar      │
└────────────────────────────────────────────────────┘
```

Auto-approve is bounded: only Tier 2/3 for direct imports of working-set files.

### 7.4 Drift Detection

Trigger warning when scope expands beyond 2x original size:

```
[SCOPE DRIFT WARNING]
Original: 4 files (1,850 tokens)
Current:  11 files (5,200 tokens) -- 2.8x expansion
Options: [C]ontinue  [R]eset  [N]ew scope
```

### 7.5 Stale Scope Detection

On activation, check file mtimes against scope creation time. Warn if source files have changed since scope was defined.

---

## 8. Multi-Agent Coordination

### 8.1 Scope Inheritance

Child agents receive parent scope as a ceiling. Three patterns:

**Identical** - Child gets parent's full scope. For delegating subtasks on the same files.

**Narrowed** - Parent partitions scope. Each child gets a subset. Prevents merge conflicts through non-overlapping write sets.

```
Parent: {parser.py, helpers/a.py, helpers/b.py, helpers/c.py}
Child A: {helpers/a.py}             -- refactor A
Child B: {helpers/b.py}             -- refactor B
Child C: {parser.py, helpers/c.py}  -- update parser + C
```

**Survey** - Explorer agents get broad read access, no write, summary-only output. They can search the codebase but return compressed results to the parent, not raw file contents.

```yaml
scope_mode: survey
permissions:
  default: existence-only
  read: "**/*.py"
  write: []
  output: summary-only
```

### 8.2 Write Conflict Prevention

Two child agents must never have overlapping write sets. Enforce hard partition by default. If partition is impossible, serialize execution (Agent A finishes before Agent B starts).

---

## 9. CLI Interface

### 9.1 Commands

```
consurg init [name]              Create a new scope (interactive)
consurg on [name]                Activate a scope
consurg off                      Deactivate current scope
consurg status                   Show active scope details
consurg map                      Visualize scope as directory tree

consurg add <files...>           Add files to working set (Tier 4)
consurg add --read <files...>    Add files as read-only (Tier 3)
consurg add --sig <files...>     Add files as signature-only (Tier 2)
consurg remove <files...>        Remove files from scope

consurg trace <entry> [--depth N]  Auto-discover scope from imports
consurg git-diff [ref]             Scope to changed files

consurg pin                      Persist scope to .consurg.yaml
consurg unpin                    Remove persisted scope

consurg enforce                  (Internal) Validate a tool call against scope
consurg adapt <tool>             Generate scope config for a specific tool
```

### 9.2 Visualization

```
$ consurg map

src/
  parser.py            [RW] ██████
  parser_helpers/
    a.py               [RW] ██████
    b.py               [RW] ██████
    c.py               [RW] ██████
  shared_types.py      [SIG] ░░░░
  config.py            [RO] ▒▒▒▒
  tokenizer.py         [RO] ▒▒▒▒
  formatter.py         [--] ----
  cli.py               [--] ----
tests/                 [--] ----
```

---

## 10. Adapters

### 10.1 Claude Code Adapter

Generates:
- CLAUDE.md scope block (Layer 1)
- `.claude/settings.local.json` hook config (Layer 2)
- `/scope` slash command

This is the primary target. Deepest integration possible.

### 10.2 Cursor Adapter

Generates:
- `.cursorrules` scope instructions
- Limitation: advisory only (Cursor's indexing is outside agent control)

### 10.3 Aider Adapter

Generates:
- `--file` and `--read` flag sets
- `.aider.conf.yml` entries

Aider already has the closest native concept. Context Surgeon adds dependency resolution and UX.

### 10.4 Generic Adapter

Outputs a structured prompt block any LLM tool can consume. Lowest common denominator but universally applicable.

---

## 11. Failure Modes

| Mode | Symptom | Cause | Recovery |
|------|---------|-------|----------|
| **Too narrow** | Agent can't complete task | Missing dependency | Guided expansion prompt |
| **Too wide** | No benefit over unscoped | Aggressive trace depth | Suggest narrowing |
| **Mismatch** | Incorrect output | Forgot config/constants file | Pre-flight dependency check |
| **Phantom** | Agent invents file contents | Tier 1 visibility without content | Structured denial, never silence |
| **Drift** | Scope eroded by expansions | Approving every request | Drift warning at 2x |
| **Stale** | Scope references moved/deleted files | Time-based staleness | Mtime check on activation |

---

## 12. Anti-Patterns (When NOT to Use)

- **Exploratory tasks**: "Understand this codebase" - requires broad access
- **Cross-cutting refactors**: "Rename X everywhere" - scope would include everything
- **Bug investigation pre-localization**: Agent needs to trace freely. Scope AFTER finding the bug.
- **Small projects**: If `total_tokens < 10 * working_set_tokens`, overhead exceeds benefit
- **Initial project setup**: Scaffolding touches many files by nature

**The two-phase rule:** Explore unscoped, execute scoped. Never skip Phase 1.

---

## 13. Economics

### 13.1 Expected Impact

| Metric | Unscoped | Scoped | Improvement |
|--------|----------|--------|-------------|
| Input tokens/turn | 7,050 | 2,400 | -66% |
| Signal ratio | 0.35 | 0.92 | +2.6x |
| Tool calls/turn | 5.2 | 2.1 | -60% |
| Task accuracy | 0.79 | 0.97 | **+23%** |

### 13.2 Selling Point Hierarchy

1. **Accuracy** (23% fewer mistakes) - the headline
2. **Speed** (60% fewer tool calls = faster sessions) - the daily experience
3. **Security** (agent physically can't read secrets) - the enterprise pitch
4. **Cost** (66% token reduction) - the least important but easiest to measure

---

## 14. Hidden Properties

**Scope definition is task decomposition.** Declaring what files matter forces you to think about what your task actually is. Side effect: you become a better engineer.

**This is secretly a security tool.** An agent that *cannot* access `.env` is safer than one *told* not to.

**Violations are signal.** Repeated boundary hits for the same file = evidence your scope is too narrow. Violation logs become expansion suggestions.

**The bootstrap problem resolves itself.** Understanding the codebase (Phase 1, unscoped) produces the knowledge needed to scope it (Phase 2). Don't scope what you haven't explored.

---

## 15. Implementation Roadmap

### Phase 1: Prompt-Only (MVP)

**Scope:** Claude Code only. Prompt injection. No enforcement hooks.
**Effort:** 1-2 days
**Deliverables:**
- `/scope` slash command that generates a scope block
- User declares files, gets CLAUDE.md-compatible output
- Tier 4 and Tier 3 only (read-write and read-only)
- Manual file listing only (no trace engine)

**Exit criteria:** A user can activate a scope in Claude Code that the agent respects via prompt compliance.

### Phase 2: Hook Enforcement

**Scope:** Claude Code plugin. PreToolUse hook. Structured denials.
**Effort:** 3-5 days
**Deliverables:**
- `consurg` Python package (installable via pip)
- Scope definition via `.consurg.yaml`
- PreToolUse hook that validates file paths (stdin JSON / exit code convention)
- Structured denial messages (JSON to stderr + exit 2)
- `consurg on/off/status/add/remove` commands
- Tiers 0, 1, 3, 4 fully enforced at hook layer
- Tier 2 enforced as block-with-hint (deny read, provide signatures in systemMessage if user pre-extracted them in YAML)
- Scope drift detection

**Exit criteria:** Out-of-scope file operations are blocked at the tool layer with actionable feedback. Tier 2 has partial support (manual signature embedding); full signature extraction deferred to Phase 3.

### Phase 3: Trace Engine + CLI

**Scope:** Multi-language import resolution. Full CLI.
**Effort:** 1-2 weeks
**Deliverables:**
- Python import resolver (production quality)
- TypeScript/JS import resolver (production quality)
- Go, Rust resolvers (basic)
- `consurg trace` command with tier auto-classification
- `consurg git-diff` command
- `consurg map` visualization
- Signature extraction (regex-based for Phase 3, tree-sitter for Phase 4)
- `consurg pin/unpin` persistence

**Exit criteria:** User can run `consurg trace src/main.py` and get a correctly tier-classified scope recommendation.

### Phase 4: Multi-Agent + Portability

**Scope:** Subagent inheritance. Tool adapters. Protocol formalization.
**Effort:** 2-3 weeks
**Deliverables:**
- Scope inheritance for Claude Code subagents (Task tool)
- Explorer exception (survey mode)
- Write conflict detection
- Cursor adapter
- Aider adapter
- Generic adapter
- Violation logging + expansion suggestions
- Tree-sitter signature extraction
- `.consurg.yaml` v1 schema published

**Exit criteria:** Scope works across multiple agent frameworks from a single `.consurg.yaml` definition.

---

## 16. Technical Stack

| Component | Technology | Rationale |
|-----------|-----------|-----------|
| Language | Python 3.10+ | Matches Claude Code plugin ecosystem, trace engine benefits from `ast` module |
| Package | pip-installable (`consurg`) | Standard distribution, also packaged as Claude Code plugin |
| Config format | YAML (human) + JSON (programmatic) | YAML for authoring, JSON for tool adapters |
| CLI framework | Typer + Rich | Already installed, provides `consurg map` visualization |
| Import resolution | `ast` module (Python), custom parsers (TS/JS), regex (Go/Rust) | Phase 3: tree-sitter for all |
| Signature extraction | Regex heuristics (Phase 2-3), tree-sitter (Phase 4) | Progressive sophistication |
| Hook integration | Claude Code PreToolUse hooks (stdin JSON, exit code) | Git hook convention, primary enforcement target |
| Hook I/O | stdin JSON input, stderr JSON + exit 2 (deny), exit 0 (allow) | Matches Claude Code hook API and pre-commit conventions |
| Testing | pytest | Standard |

### 16.1 Plugin Package Structure

```
consurg/
├── .claude-plugin/
│   └── plugin.json              # Plugin manifest
├── hooks/
│   ├── hooks.json               # PreToolUse hook config
│   └── enforce.py               # Scope enforcement script
├── commands/
│   ├── scope.md                 # /scope slash command (Phase 1)
│   ├── scope-status.md          # /scope-status command
│   └── scope-map.md             # /scope-map command
├── skills/
│   └── context-surgeon/
│       └── SKILL.md             # Skill documentation
├── consurg/                     # Python package (pip-installable)
│   ├── __init__.py
│   ├── cli.py                   # Typer CLI entry point
│   ├── scope.py                 # Scope loading, validation, drift detection
│   ├── enforce.py               # Tier resolution and enforcement logic
│   ├── trace/                   # Trace engine (Phase 3)
│   │   ├── __init__.py
│   │   ├── graph.py             # DependencyGraph + DependencyKind
│   │   ├── python_resolver.py
│   │   ├── ts_resolver.py
│   │   └── signatures.py        # Signature extraction
│   └── adapters/                # Tool adapters (Phase 4)
│       ├── __init__.py
│       ├── claude.py
│       ├── cursor.py
│       ├── aider.py
│       └── generic.py
├── pyproject.toml               # Package metadata + dependencies
└── tests/
    ├── test_scope.py
    ├── test_enforce.py
    └── test_trace.py
```

`${CLAUDE_PLUGIN_ROOT}` resolves to the plugin root, so `hooks/enforce.py` can import from the `consurg/` package by adding the plugin root to `sys.path`.

---

## 17. Open Design Decisions

| Decision | Options | Leaning | Rationale |
|----------|---------|---------|-----------|
| Scope storage location | `.consurg.yaml` in project root vs `.claude/scope.yaml` | Project root | Visible, portable, not Claude-specific |
| Default tier for unlisted files | Tier 0 (blocked) vs Tier 1 (existence) | Tier 0 | Strictest default, opt-in to visibility |
| Auto-include test files | Always, never, `--with-tests` flag | Flag | Tests are a common need but not universal |
| Barrel file resolution | Trace through vs treat as single file | Trace through | Barrel files are context traps |
| Scope names | Required vs auto-generated | Auto-generated with optional override | Reduce friction for quick scoping |
| Glob tool behavior under scope | Allow all (paths aren't content) vs filter results | Allow all | Glob returns paths only; blocking it cripples navigation. Tier 0 still blocks Read. |
| Tier 2 in Phase 2 | Block read + hint in systemMessage vs allow full read | Block + hint | Full Tier 2 (content transformation) requires Phase 3 proxy layer |
| Windows compatibility | Git Bash wrapper vs native Python | Native Python | `enforce.py` is pure Python, no shell dependency. Avoids Git Bash requirement. |

### Resolved Decisions

| Decision | Resolution | Locked in |
|----------|-----------|-----------|
| Hook I/O contract | stdin JSON input, stderr JSON + exit 2 for deny, exit 0 for allow | Phase 2 |
| Hook tool data delivery | Via stdin (not env vars) - matches Claude Code hook API | Phase 2 |
| CLI command pattern | Flat (`consurg add`, not `consurg scope add`) | Phase 1 |
| YAML schema versioning | `version: 1` field in `.consurg.yaml` | Phase 1 |

---

## 18. Success Metrics

**Phase 1:**
- Can activate scope in <30 seconds
- Agent stays in scope for 90%+ of operations (prompt compliance)

**Phase 2:**
- 100% enforcement (zero out-of-scope file modifications)
- <5% false positive rate (legitimate operations incorrectly blocked)

**Phase 3:**
- Trace engine correctly classifies 90%+ of Python imports on first run
- Scope recommendation accepted without edits 70%+ of the time

**Phase 4:**
- Works with 3+ agent tools from single config
- Multi-agent scope inheritance prevents 100% of write conflicts
