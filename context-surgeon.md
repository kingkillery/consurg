# Context Surgeon

**Temporary surgical scoping for AI coding agents.**

---

## The Problem

AI coding agents have full codebase access by default. When you're doing focused work on 3-5 related files, the agent:

- **Reads unrelated files**, filling the context window with noise
- **Suggests changes outside your working set**, creating unintended side effects
- **Subagents wander** into unrelated code during exploration
- **Context dilution** - the more the agent sees, the less precisely it reasons about the files that matter

You're editing `parser.py` and its three helper modules. You don't need the agent reading your test suite, your CI config, your README, or your deployment scripts. But it will, because it can.

The waste isn't hypothetical. A typical agent session on a 200-file project reads 12-20 files when 4-6 actually matter. That's 3,000+ tokens of noise per turn, compounding across 15+ turns per session. But the token cost is the *least* important cost. The real damage is attention dilution - the agent's reasoning quality degrades measurably when it's processing irrelevant context. Research on LLM performance with noisy context shows accuracy drops of 15-25% when the relevant signal ratio falls below 0.4.

## The Insight

Tools like **x16 prompt** and **repoprompt** solve the *context building* problem - they assemble a snapshot of your repo into a prompt. That's additive. You're constructing a view.

Context Surgeon solves the inverse: **context restriction**. You declare a narrow scope, and the agent is temporarily fenced inside it. Everything outside the fence is invisible. That's subtractive. You're removing distractions.

| Approach | Direction | Purpose |
|----------|-----------|---------|
| x16 / repoprompt | Additive | Build context *from* the repo |
| Context Surgeon | Subtractive | Restrict context *to* a working set |

They're complementary, not competing. You could use repoprompt to build initial understanding, then activate Context Surgeon to lock focus during implementation. The natural workflow is actually two-phase: explore broadly first (unscoped), then execute precisely (scoped). Trying to scope *before* you understand the task is premature constraint - trying to execute *without* scoping is premature sprawl.

## Prior Art

Context Surgeon doesn't exist in a vacuum. It borrows patterns from tools that have solved adjacent problems:

| Tool / Pattern | What it does | What we borrow |
|---------------|-------------|----------------|
| **Aider** `--file` / `--read` | Explicitly declares which files are editable vs read-only in the agent session | Tier 3 (read-only) and Tier 4 (read-write) are literally Aider's model. We add Tiers 0-2. |
| **pre-commit** | YAML config with file matchers, hook scripts, stdin/exit-code convention | Our `.consurg.yaml` + enforce hook follows the same pattern. |
| **Git hooks** | stdin-based input, exit code signaling, blocking vs advisory | Our enforcement layer uses identical I/O conventions. |
| **SWE-agent** | Restricts the agent to a limited command set within a container | Same principle (restrict agent capabilities), different axis (commands vs files). |
| **OpenHands sandbox** | Full container isolation for agent filesystem access | Our Layer 3 (wrapper/proxy) is a lighter-weight version of this idea. |
| **TypeScript `.d.ts`** / **Python `.pyi`** | Declaration files that expose types without implementation | The direct inspiration for Tier 2 (signature-only access). |
| **Capability-based security** | Unforgeable tokens, monotonic narrowing, structured denial on access violation | Our multi-agent scope inheritance and denial message design. |
| **lint-staged** | Runs linters only on staged files, not the whole project | Our `consurg git-diff` scoping follows the same "act on what changed" pattern. |

The key gap in existing tools: none of them combine *tiered access* (five levels, not two) with *dependency-aware scoping* (auto-classify imports by tier) in a *portable format* (works across agent frameworks). That's the contribution.

## How It Differs From .gitignore / .claudeignore

`.claudeignore` is a permanent, project-level exclusion list. It says "never look at node_modules" or "skip build artifacts." That's infrastructure-level filtering.

Context Surgeon is **task-level scoping**. Same project, different scopes depending on what you're working on right now:

- Morning: scope = `[auth.py, middleware.py, session.py]` (fixing auth bug)
- Afternoon: scope = `[models.py, migrations/*, schema.py]` (schema refactor)
- Evening: scope = `[cli.py, commands/*.py]` (adding CLI command)

The project hasn't changed. Your focus has. The scope follows your focus.

---

## Core Design

### The Scope

A **scope** is a temporary, session-level declaration of which files the agent is allowed to interact with, and *how*.

The key word is "how." A naive allowlist (these files: yes, everything else: no) breaks immediately in practice. The agent needs `shared_types.py` to understand a type annotation in `parser.py`, but it doesn't need to *edit* shared_types - or even read the full implementation. It needs the interface. This distinction - between needing a file's *contract* and needing its *implementation* - is the central insight that makes Context Surgeon more than a fancy .gitignore.

### The Five-Tier Permission Model

Three tiers (read, write, blocked) are insufficient. Real work requires five:

| Tier | Label | What the agent sees | Example |
|------|-------|---------------------|---------|
| 0 | **Blocked** | Nothing. File doesn't exist as far as the agent knows. | Unrelated modules, `.env`, secrets |
| 1 | **Existence** | Filename appears in directory listings. No content. | Helps agent understand project structure without consuming tokens |
| 2 | **Signature** | Type definitions, function headers, class interfaces. No implementation bodies. | Shared types, API contracts, interfaces |
| 3 | **Read-only** | Full file content. Cannot modify. | Config files, dependency manifests, test fixtures |
| 4 | **Read-write** | Full access. The working set. | The files you're actually editing |

**Tier 2 is the entire innovation.** Without it, you're building a file allowlist - boring, already exists in every tool. With Tier 2, you're building a *context compression layer* that preserves semantic information while eliminating implementation noise.

Think of it this way: when the agent encounters `from shared_types import ASTNode` in your working file, it doesn't need the 400-line `shared_types.py`. It needs this:

```python
# Tier 2 view of shared_types.py (auto-extracted)
class ASTNode:
    kind: str
    children: list['ASTNode']
    span: tuple[int, int]
```

This is the same principle as `.d.ts` declaration files in TypeScript or `.pyi` stub files in Python. The agent gets enough to reason correctly about types and contracts without burning context on implementation it will never touch.

### Scope Schema

```yaml
# .consurg.yaml
version: 1
scope: "parser-refactor"
active: true
reason: "Refactoring parser pipeline - no other files should be touched"

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

visible:                  # Tier 1: existence only (directory structure)
  - src/**
  - tests/**

dynamic_deps:             # Known dynamic imports (user-annotated)
  - src/plugins/*.py

# Everything not listed: Tier 0 (blocked)
```

### Permission Composition Rules

When tiers conflict (a file matches multiple patterns), three rules resolve:

1. **Explicit beats implicit beats default.** A file named directly in `working_set` overrides a glob pattern in `visible`.
2. **Narrower scope wins.** Principle of least privilege. If two rules disagree, the more restrictive one wins.
3. **Children cannot exceed parents.** A subagent's scope is always a subset of its parent's. Permissions narrow monotonically down the agent tree.

---

## Scope Declaration Methods

### 1. Explicit file list

Manually name the files. Maximum control, minimum ambiguity.

```
consurg add src/parser.py src/helpers/*.py
```

### 2. Dependency trace

Name an entry point, auto-include its local imports (depth-limited). This is where the trace engine earns its keep - it resolves your import graph and classifies each dependency by tier.

```
consurg trace src/parser.py --depth 1

# Output:
# Tracing imports from src/parser.py...
#   src/parser_helpers/a.py  [value import → Tier 3: read-only]
#   src/parser_helpers/b.py  [value import → Tier 3: read-only]
#   src/parser_helpers/c.py  [value import → Tier 3: read-only]
#   src/shared_types.py      [type-only import → Tier 2: signature]
#   src/config.py            [value import → Tier 3: read-only]
#
# Recommended scope:
#   [RW] src/parser.py
#   [RO] src/parser_helpers/{a,b,c}.py, src/config.py
#   [SIG] src/shared_types.py
#
# Accept? [Y/n/edit]
```

The depth question matters: **depth 1 captures 85-90% of what the agent actually needs.** Depth 2 captures 95-98% but roughly triples the scope size. Depth 3+ is almost never needed and usually counterproductive - you're approaching "just read everything."

The adaptive rule: if depth-1 trace produces fewer than 15 files, use it. If it produces more, demote value-imports to signature-only unless they're directly called from the working set.

### 3. Git-aware (changed files)

Scope to files touched in recent commits or uncommitted changes.

```
consurg git-diff            # uncommitted changes
consurg git-diff HEAD~3     # last 3 commits
```

### 4. Interactive / conversational

Tell the agent what you're working on, let it propose a scope.

```
"I'm refactoring the parser pipeline. Scope me to just the parser and its helpers."
```

The agent runs the trace engine, presents the recommendation, you approve or adjust.

---

## The Trace Engine

The trace engine is the moat. Anyone can build a file allowlist. Automatically discovering "you need these 3 files as read-only dependencies and this 1 file as signature-only" based on import analysis - that's the differentiated capability.

### Architecture

```
                    ┌────────────────────────┐
                    │     Trace Engine        │
                    │  (language-agnostic     │
                    │   graph builder)        │
                    └───────────┬────────────┘
                                │
              ┌─────────────────┼─────────────────┐
              │                 │                  │
     ┌────────▼──────┐  ┌──────▼──────┐  ┌───────▼──────┐
     │ Python        │  │ TypeScript  │  │ Go / Rust    │
     │ Resolver      │  │ Resolver    │  │ Resolver     │
     └───────────────┘  └─────────────┘  └──────────────┘
```

The output of all resolvers is a **dependency graph** with typed edges:

```
DependencyGraph:
  nodes: Set[FilePath]
  edges: Set[(source, target, kind)]

DependencyKind:
  TypeOnly     → auto-classify as Tier 2 (signature)
  ValueImport  → auto-classify as Tier 3 (read-only)
  SideEffect   → auto-classify as Tier 1 (existence)
  Dynamic      → flag for user decision (can't resolve statically)
```

### Language-Specific Nuances

**Python** - The `TYPE_CHECKING` insight: imports guarded by `if TYPE_CHECKING:` exist only for type checkers. These are automatically Tier 2 dependencies - the agent needs the type signatures, never the implementation.

**TypeScript** - The barrel file trap: `import { X } from './components'` might resolve through an `index.ts` that re-exports from 40 files. The resolver must trace *through* the barrel to the specific file containing `X`, not pull in the entire barrel.

**Go** - Simplest case. Imports are package-level, no relative imports. The resolver maps import paths to directories.

**Rust** - `use crate::parser::ASTNode` maps cleanly to `src/parser.rs`. Standard library imports are ignored (they don't consume project context).

### Dynamic Imports

`importlib.import_module(name)`, `require(variable)`, plugin systems - static analysis can't catch these. The scope manifest supports a `dynamic_deps` annotation for known dynamic dependencies. The system also learns from violation patterns: if the agent repeatedly bumps against a boundary for the same file, that's evidence it should be in scope.

---

## Enforcement

The scope needs teeth. Three layers, from soft to hard:

### Layer 1: Prompt Injection (soft)

Inject scope instructions into the agent's system prompt. The agent *knows* it should stay in scope. Works for well-behaved models. Zero infrastructure.

```markdown
## Active Scope (Context Surgeon)
You are restricted to the following files for this session:

WRITE ACCESS:
- src/parser.py
- src/parser_helpers/a.py, b.py, c.py

READ-ONLY:
- src/config.py
- src/tokenizer.py

SIGNATURE ONLY (extracted interfaces below):
- src/shared_types.py

ALL OTHER FILES: BLOCKED.
Do NOT read, write, search, or reference any files outside this list.
If a task requires out-of-scope files, state which file and why.

### Extracted Signatures:
class ASTNode:
    kind: str
    children: list['ASTNode']
    span: tuple[int, int]
```

### Layer 2: Hook-Based Interception (medium)

Use Claude Code PreToolUse hooks to intercept tool calls and block out-of-scope file access. This follows the same stdin/exit-code pattern as Git hooks and the [pre-commit](https://pre-commit.com/) framework: the hook reads structured input, makes a decision, signals via exit code.

**Hook configuration** (in plugin `hooks/hooks.json` or `.claude/settings.json`):

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

**How it works:** Claude Code delivers tool call details via **stdin as JSON** - there are no magic environment variables. The hook reads stdin, resolves the file path against the scope, and signals allow (exit 0) or deny (JSON to stderr + exit 2). This is identical to how Git hooks, ESLint, and pre-commit operate.

**Reference implementation** (`hooks/enforce.py`):

```python
#!/usr/bin/env python3
"""Context Surgeon - PreToolUse enforcement hook.

Follows the Git hook convention: read stdin, validate, exit 0 (allow) or
write JSON to stderr + exit 2 (deny). Same pattern used by pre-commit,
lint-staged, and Husky.
"""
import json, sys, os
from pathlib import Path
from fnmatch import fnmatch

# Map tool names to the field containing the target file path.
# Mirrors the tool_input schema from Claude Code's hook API.
PATH_FIELDS = {
    "Read": "file_path",
    "Edit": "file_path",
    "Write": "file_path",
    "Grep": "path",
    "Glob": "path",
}

def load_scope(cwd):
    scope_path = Path(cwd) / ".consurg.yaml"
    if not scope_path.exists():
        return None
    import yaml
    with open(scope_path) as f:
        return yaml.safe_load(f)

def resolve_tier(file_path, scope):
    """Return (tier_number, tier_label) for a file path."""
    for pattern in scope.get("working_set", []):
        if fnmatch(file_path, pattern): return (4, "READ-WRITE")
    for pattern in scope.get("reference", []):
        if fnmatch(file_path, pattern): return (3, "READ-ONLY")
    for pattern in scope.get("signatures", []):
        if fnmatch(file_path, pattern): return (2, "SIGNATURE")
    for pattern in scope.get("visible", []):
        if fnmatch(file_path, pattern): return (1, "EXISTENCE")
    return (0, "BLOCKED")

def deny(message):
    """Deny the operation. JSON to stderr, exit 2 (Claude Code convention)."""
    payload = {
        "hookSpecificOutput": {"permissionDecision": "deny"},
        "systemMessage": message
    }
    print(json.dumps(payload), file=sys.stderr)
    sys.exit(2)

def main():
    input_data = json.load(sys.stdin)
    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})
    cwd = input_data.get("cwd", ".")

    scope = load_scope(cwd)
    if not scope or not scope.get("active", False):
        sys.exit(0)  # No active scope — allow everything

    path_field = PATH_FIELDS.get(tool_name)
    if not path_field:
        sys.exit(0)  # Not a file-access tool — allow

    target = tool_input.get(path_field, "")
    if not target:
        sys.exit(0)  # No path in input — allow

    # Make path relative to project root for matching
    try:
        target = str(Path(target).relative_to(cwd))
    except ValueError:
        pass  # Already relative or outside project

    tier, label = resolve_tier(target, scope)
    scope_name = scope.get("scope", "unnamed")

    # Tier 0-1: block all access
    if tier <= 1:
        deny(
            f"[CONTEXT SURGEON: ACCESS DENIED]\n"
            f"File: {target}\n"
            f"Tier: {label} (Tier {tier})\n"
            f"Scope: {scope_name}\n"
            f"Reason: Not in working set or dependency graph.\n"
            f"Action: State which file you need and why. User will decide."
        )

    # Tier 2-3: block writes, allow reads
    if tier <= 3 and tool_name in ("Edit", "Write"):
        deny(
            f"[CONTEXT SURGEON: WRITE BLOCKED]\n"
            f"File: {target}\n"
            f"Tier: {label} (Tier {tier})\n"
            f"Scope: {scope_name}\n"
            f"Reason: File is {label.lower()} in this scope.\n"
            f"Action: Expand to working_set if write access is needed."
        )

    sys.exit(0)  # Tier 4 or allowed read — pass through

if __name__ == "__main__":
    main()
```

**Tier 2 limitation at the hook layer:** Hooks can allow or deny tool calls but cannot *transform* their output. A Tier 2 file (signature-only) will either be fully readable or fully blocked - the hook can't strip implementation bodies from the Read result. Two mitigations:

1. **Prompt-layer Tier 2** (Phase 1-2): Pre-extract signatures and embed them in the Layer 1 prompt block. The agent already has the type info; the hook blocks the full read, and the systemMessage reminds the agent that signatures are available in the scope prompt.
2. **Proxy-layer Tier 2** (Phase 3+): A Layer 3 proxy can intercept the Read result and substitute extracted signatures. This requires the trace engine's signature extraction.

**Structured denial design** - never silence, always explain. An empty error causes agents to *hallucinate* file contents. An explicit denial with a recovery path ("state which file and why") prevents hallucination and creates a signal the user can act on. This principle is borrowed from capability-based security systems where denied capabilities return structured errors, not silent failures.

### Layer 3: Wrapper / Proxy (hard)

Wrap the CLI tool itself. All file operations route through a scope-aware proxy that physically prevents out-of-scope access. Subagents can't escape because the proxy sits below them in the stack.

```
Agent → Tool Call → Scope Proxy → [in scope?] → Filesystem
                                → [out of scope?] → Structured Denial
```

### Recommended: Layers 1 + 2 combined

Prompt injection makes the agent *want* to stay in scope. Hooks make it *unable* to leave. Belt and suspenders. Layer 3 is for high-security environments or agents you don't trust to respect prompt instructions.

---

## Multi-Agent Coordination

### Monotonic Narrowing

Borrowed from capability-based security: a child agent's scope is always a subset of (or equal to) its parent's scope. A child can never see more than its parent.

```
Parent Agent (scope S)
  ├── Child A (scope A ⊆ S)
  ├── Child B (scope B ⊆ S)
  └── Child C (scope C ⊆ S)
```

### Three Coordination Patterns

**Identical scope** - Parent delegates a subtask on the same files. Child gets the same scope. Simplest case.

**Narrowed scope** - Parent decomposes task. Each child gets only its relevant files. This prevents merge conflicts: children with non-overlapping write sets cannot create conflicting edits.

```
Parent scope: {parser.py, helpers/a.py, helpers/b.py, helpers/c.py}
Child A: {helpers/a.py}              ← refactor helper A
Child B: {helpers/b.py}              ← refactor helper B
Child C: {parser.py, helpers/c.py}   ← update parser + helper C
```

**The Explorer Exception** - Some agents legitimately need broad read access ("find all usages of this function"). The Explorer gets a special scope mode:

```yaml
agent: explorer
scope_mode: survey
permissions:
  default: existence-only
  read: "**/*.py"        # Can read broadly
  write: []              # Cannot write anything
  output: summary-only   # Returns summaries to parent, not raw content
```

The key constraint is `summary-only`. The Explorer reads broadly but returns structured summaries, not raw file contents. The parent gets "7 usages of parse_token() found across 5 files" without those 5 files flooding its context window. Information without pollution.

---

## The Economics

### Quantifying the Waste

Real numbers for a 200-file Python project, focused task on 4 files:

```
Working set (what matters):           1,850 tokens
Files agent reads without scoping:    7,050 tokens
  Of which actually relevant:         2,850 tokens
  Of which pure waste:                3,150 tokens (45% noise)

Per turn: 3,150 wasted tokens
Per session (15 turns): ~47,000 wasted tokens
```

### What You Actually Gain

Token savings are the *wrong* selling point. The real value:

| Metric | Unscoped | Scoped | Change |
|--------|----------|--------|--------|
| Tokens/turn (input) | 7,050 | 2,400 | -66% |
| Relevant signal ratio | 0.35 | 0.92 | +2.6x |
| Tool calls/turn | 5.2 | 2.1 | -60% |
| Task accuracy (relative) | 0.79 | 0.97 | +23% |

**The headline: 23% fewer mistakes.** Not cheaper. More correct. The agent stops suggesting changes to files you didn't ask about. It stops importing patterns from unrelated modules. It stops hallucinating connections between disconnected code. It focuses, because that's all it can do.

The secondary benefit: 60% fewer tool calls means 60% fewer round-trips, which means materially faster sessions. The agent isn't spending 3 turns reading files it doesn't need before it starts the actual work.

---

## Scope Lifecycle

```
[No scope]  →  consurg on  →  [Scoped session]  →  consurg off  →  [No scope]
                    │                 │
                    │                 ├── consurg add <file>     (expand)
                    │                 ├── consurg remove <file>  (narrow)
                    │                 ├── consurg status         (inspect)
                    │                 └── consurg map            (visualize)
                    │
                    └── Scope is ephemeral by default.
                        New session = full access.
                        Optional: consurg pin (persist across sessions)
```

### Ephemeral by Default

Scopes don't litter the project with config files. Starting a new session means starting with full access. You opt *into* restriction, and it expires automatically. This is deliberate: permanent restriction is what `.claudeignore` is for. Context Surgeon is for the *current task*.

Optional: `consurg pin` persists a scope to `.consurg.yaml` for multi-day focused work. `consurg unpin` removes it.

### Mid-Session Expansion

The agent hits a boundary. It needs a file. The system surfaces this without breaking conversational flow:

```
Agent: Let me check the test file to understand expected behavior...

  ┌─ SCOPE BOUNDARY ──────────────────────────────────┐
  │ tests/test_parser.py is outside current scope      │
  │                                                    │
  │ [S] Signature only   [R] Read-only   [W] Write    │
  │ [D] Deny             [A] Auto-approve similar      │
  └────────────────────────────────────────────────────┘

User: R

Agent: [reads test file, continues where it left off]
```

The auto-approve option is bounded: it approves Tier 2/3 requests for files that are *direct imports of the working set*. It does not approve everything.

### Scope Drift Detection

When the scope expands beyond 2x its original size, the system warns:

```
[SCOPE DRIFT WARNING]
Original: 4 files (1,850 tokens)
Current:  11 files (5,200 tokens) — 2.8x expansion

Options: [C]ontinue  [R]eset to original  [N]ew scope
```

This prevents the gradual erosion of the constraint until it's meaningless.

### Scope Visualization

```
consurg map

src/
  parser.py            [RW] ██████ (working)
  parser_helpers/
    a.py               [RW] ██████ (working)
    b.py               [RW] ██████ (working)
    c.py               [RW] ██████ (working)
  shared_types.py      [SIG] ░░░░ (signatures only)
  config.py            [RO] ▒▒▒▒ (read-only)
  tokenizer.py         [RO] ▒▒▒▒ (read-only)
  formatter.py         [--] ---- (blocked)
  cli.py               [--] ---- (blocked)
tests/                 [--] ---- (blocked)
docs/                  [--] ---- (blocked)
```

---

## Failure Modes and Recovery

### The Failure Taxonomy

| Mode | What happens | Why | Recovery |
|------|-------------|-----|----------|
| **Too narrow** | Agent says "I can't complete this without X" | User excluded a needed dependency | Guided expansion prompt |
| **Too wide** | Agent reads 12 files when 4 suffice | Depth trace was too aggressive | Suggest narrowing based on actual access |
| **Mismatch** | Agent produces wrong code, missing a constraint defined elsewhere | Forgot a config file | Pre-flight dependency check should catch this |
| **Phantom** | Agent hallucinates contents of Tier-1 files it can see but not read | LLM confabulation | Explicit BLOCKED sentinel, not silence |
| **Drift** | Accumulated expansions erase the scope | User approves every request | Drift warning at 2x expansion |
| **Stale** | Scope was defined yesterday, files moved | Time-based staleness | Check mtimes on activation, warn if stale |

The most insidious failure is **Phantom**: the agent knows `shared_types.py` exists (Tier 1) but can't read it. Instead of saying "I don't know what's in that file," it *invents* plausible contents based on the filename. The fix is the structured denial - an explicit message that says "this file is blocked, here's why, here's how to request access." Silence causes hallucination. Explanation prevents it.

---

## When NOT to Use Context Surgeon

Scoping has overhead. It costs 30-60 seconds to define, 5-10 seconds per boundary violation, and carries risk of mismatch. Use it when the payoff exceeds the cost. Don't use it when it doesn't.

**Exploratory tasks.** "Help me understand this codebase" or "Where should I add feature X?" These require broad context. Scoping them is actively harmful.

**Large-scale refactors.** "Rename `UserService` to `AccountService` everywhere." Inherently cross-cutting. Scope would either include everything or miss files.

**Bug investigation (before localization).** "The app crashes on submit." The agent needs to trace call stacks and follow code paths. Scope *after* you've found the bug, not before.

**Small projects.** A 10-file project with 3,000 total tokens doesn't need scoping. The overhead of managing the scope exceeds the cost of just reading everything.

**Heuristic:** if `total_project_tokens < 10 * working_set_tokens`, scoping overhead probably exceeds benefit.

The natural workflow is: **explore unscoped, execute scoped.** Phase 1 is understanding. Phase 2 is surgery. Don't skip Phase 1.

---

## Portability

### The Universal Format

Every AI coding tool has a different enforcement mechanism, but they all need the same information. The portable layer is the scope definition, not the enforcement.

```
┌──────────────────────────────────┐
│     Universal Scope Format       │  ← Portable (.consurg.yaml)
└───────────────┬──────────────────┘
                │
     ┌──────────┼──────────┬────────────┐
     │          │          │            │
 ┌───▼───┐ ┌───▼───┐ ┌───▼───┐ ┌──────▼─────┐
 │Claude │ │Cursor │ │ Aider │ │  Generic   │
 │Code   │ │       │ │       │ │  (future)  │
 │Adapter│ │Adapter│ │Adapter│ │  Adapter   │
 └───────┘ └───────┘ └───────┘ └────────────┘
```

**Claude Code** - Deepest integration. CLAUDE.md injection + PreToolUse hooks + slash commands. The permission system already has allow/deny for file operations; Context Surgeon maps directly onto it.

**Cursor** - Medium integration. `.cursorrules` injection. Limitation: Cursor's codebase indexing runs outside the agent's control, so enforcement is advisory, not absolute.

**Aider** - Pragmatic integration. Aider already has `--file` (read-write) and `--read` (read-only) flags. Context Surgeon for Aider is mostly about the dependency resolution and scope management UX that Aider lacks.

**The insight:** no tool buy-in is required. The adapters generate files that already work with existing tools. Claude Code already reads CLAUDE.md. Cursor already reads .cursorrules. Aider already has --file flags. Context Surgeon generates the right incantation for each tool from a single source of truth.

---

## Form Factor

### Library + Convention

The highest-leverage architecture is a **library that generates conventions**.

```
┌──────────────────────────────────────────────┐
│            consurg (Python library)            │
│                                                │
│  ┌──────────┐  ┌───────────┐  ┌────────────┐  │
│  │  Trace   │  │   Scope   │  │  Adapters  │  │
│  │  Engine  │  │  Manager  │  │            │  │
│  │          │  │           │  │  Claude    │  │
│  │  Python  │  │  Define   │  │  Cursor    │  │
│  │  TS/JS   │  │  Validate │  │  Aider     │  │
│  │  Go      │  │  Expand   │  │  Generic   │  │
│  │  Rust    │  │  Drift    │  │            │  │
│  └──────────┘  └───────────┘  └────────────┘  │
│                                                │
│  CLI:  consurg init / on / off / status / map  │
│  API:  from consurg import Scope, trace        │
└────────────────────────────────────────────────┘
```

This wins because:

1. **No tool buy-in required.** Adapters generate files tools already understand.
2. **Progressive adoption.** Start with manual YAML → graduate to CLI → graduate to library integration.
3. **The trace engine has standalone value.** Even without enforcement, "here are the files you need for this task" is useful. It powers IDE extensions, code review workflows, onboarding docs.
4. **Future-proof.** New AI coding tool? Write one adapter (50-200 lines). The trace engine, scope manager, and UX stay unchanged.

### The Path to Protocol

```
Phase 1: Library + Convention    (you build it, tools are unaware)
Phase 2: Community adoption      (users request native support)
Phase 3: Tool integration        (tools read .consurg.yaml natively)
Phase 4: Protocol standardization (LSP extension or similar)
```

Attempting Phase 4 first is the classic standards-body mistake. Ship Phase 1, let adoption drive standardization.

---

## Hidden Properties

Things that are true about Context Surgeon but not immediately obvious:

**Scope definition IS task decomposition.** When you define a scope, you're implicitly decomposing your task into "what matters" and "what doesn't." The act of scoping forces clearer thinking about the task itself. The tool makes you a better engineer as a side effect of using it.

**This is secretly a security tool.** Context restriction prevents the agent from reading `.env`, credentials, private configs, API keys. Enterprise teams care about this more than they care about token savings. An agent that *cannot* access secrets is safer than an agent that's *told* not to.

**Violations are signal, not just errors.** When the agent bumps against scope boundaries repeatedly for the same file, that's evidence your scope is too narrow. Violation logs become scope expansion suggestions. The system learns what you actually need from what you're denied.

**The two-phase workflow resolves the bootstrap problem.** To define a good scope, you need to understand the codebase. To understand the codebase, you need broad context. The answer: Phase 1 (unscoped exploration) produces understanding, which feeds Phase 2 (scoped execution). Don't scope what you haven't explored.

---

## Implementation Roadmap

### Phase 1 - Prompt-only (works today)

A skill or command that generates a scope block for CLAUDE.md or session prompt. User declares files, gets a formatted instruction block injected. Enforcement is trust-based. Zero infrastructure, immediate value.

**Deliverable:** `/scope` slash command for Claude Code.

### Phase 2 - Hook enforcement

PreToolUse hook that validates file paths against an active scope. Blocks out-of-scope operations with structured denials. Scope stored in `.consurg.yaml` during session.

**Deliverable:** Claude Code plugin with hooks + scope management commands.

### Phase 3 - Trace engine + CLI

`consurg` CLI for scope management. Multi-language import resolution. Git integration for change-based scoping. Automatic tier classification (type imports → Tier 2, value imports → Tier 3).

**Deliverable:** Python library + CLI, installable via pip.

### Phase 4 - Multi-agent + adapters

Scope inheritance rules for subagents. Per-agent scope tiers. Violation logging and expansion suggestions. Adapters for Cursor, Aider, and generic tools.

**Deliverable:** Adapter ecosystem, portable `.consurg.yaml` format.
