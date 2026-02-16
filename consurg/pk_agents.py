from __future__ import annotations

from pathlib import Path

AGENT_DIR = Path(".agents") / "pk-agents"

SCOPE_SELECTOR_AGENT = """---
model: anthropic:claude-sonnet-4-5
description: "Classify repository files into include, read_only, and exclude for a specific coding request."
timeout: 600
maxSteps: 80
---

# Consurg Scope Selector Agent

You are the scope-classification agent for Context Surgeon.

## Objective
Given a user task request, inspect this repository and propose:
1. Files to include in active coding context (`include_context`)
2. Files to allow as read-only (`read_only`)
3. Files to exclude entirely (`exclude`)

## Rules
- Prioritize minimal context that still enables safe implementation.
- Use concrete repo-relative paths (or narrow glob patterns).
- If uncertain, classify as `read_only` before `exclude`.
- Keep build/test/config files read-only unless edits are required.
- Exclude generated artifacts, caches, vendor directories, and unrelated domains.

## Required Workflow
1. Read `TASK_REQUEST.md` from project root.
2. Inventory files with `rg --files`.
3. Use targeted code search with `rg -n` to discover call paths and dependencies.
4. Produce `.consurg/recommendations/scope-proposal.yaml` with:
   - `task`
   - `include_context`
   - `read_only`
   - `exclude`
   - `rationale`
   - `risks`
5. Also emit `.consurg/recommendations/scope-proposal.md` summarizing why each list exists.

## Output Contract
Never skip the output files. If any section is empty, write an empty list.
"""

EXCLUDED_SUMMARIZER_AGENT = """---
model: anthropic:claude-sonnet-4-5
description: "Summarize excluded files so implementation agents know what exists and why it is out-of-scope."
timeout: 600
maxSteps: 80
---

# Consurg Excluded Files Summarizer Agent

You are the excluded-context review agent for Context Surgeon.

## Objective
Review files listed in `exclude` from `.consurg/recommendations/scope-proposal.yaml`.
Create a high-signal summary for implementation agents so they:
1. Know excluded files exist
2. Understand how those files affect the overall system
3. Understand why those files are unnecessary for the current task

## Required Workflow
1. Read:
   - `TASK_REQUEST.md`
   - `.consurg/recommendations/scope-proposal.yaml`
2. For each excluded path (or glob), inspect enough code to understand responsibilities.
3. Group excluded files into domains/subsystems.
4. Write `.consurg/recommendations/excluded-context.md` with sections:
   - `## Excluded Surface Area`
   - `## System Influence`
   - `## Why Excluded For This Task`
   - `## Re-entry Triggers`

## Quality Bar
- Be concrete about boundaries and cross-module dependencies.
- Call out any hidden risk where excluded code could still affect the task.
- Keep the summary concise and implementation-oriented.
"""

RUNBOOK = """# Consurg pk-agent Scope Workflow

This scaffold creates two agents:

1. `consurg-scope-selector.pk-agent`
2. `consurg-excluded-summarizer.pk-agent`

## 1) Write the task request

Create `TASK_REQUEST.md` in the project root describing the coding task.

## 2) Run the scope selector

```bash
pk-agent run .agents/pk-agents/consurg-scope-selector.pk-agent
```

Expected outputs:
- `.consurg/recommendations/scope-proposal.yaml`
- `.consurg/recommendations/scope-proposal.md`

## 3) Run the excluded summarizer

```bash
pk-agent run .agents/pk-agents/consurg-excluded-summarizer.pk-agent
```

Expected output:
- `.consurg/recommendations/excluded-context.md`

## 4) Apply results to Consurg scope

Map the proposal into `.consurg.yaml`:
- `include_context` -> `working_set`
- `read_only` -> `reference`
- `exclude` -> implicit Tier 0 blocked
"""


def scaffold_pk_agents(project_root: Path, force: bool = False) -> list[Path]:
    agent_dir = project_root / AGENT_DIR
    output_dir = project_root / ".consurg" / "recommendations"
    output_dir.mkdir(parents=True, exist_ok=True)
    agent_dir.mkdir(parents=True, exist_ok=True)

    files = {
        agent_dir / "consurg-scope-selector.pk-agent": SCOPE_SELECTOR_AGENT,
        agent_dir / "consurg-excluded-summarizer.pk-agent": EXCLUDED_SUMMARIZER_AGENT,
        agent_dir / "README.md": RUNBOOK,
    }

    written: list[Path] = []
    for path, content in files.items():
        if path.exists() and not force:
            continue
        path.write_text(content, encoding="utf-8")
        written.append(path)
    return written
