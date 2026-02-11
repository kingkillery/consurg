# Getting Started

## Prerequisites

- Python 3.10 or later
- pip

## Installation

```bash
git clone https://github.com/kingkillery/consurg.git
cd consurg
pip install -e .
```

Verify the install:

```bash
consurg --help
```

You should see all available commands listed.

## Your First Scope

### 1. Initialize

Navigate to your project and create a scope:

```bash
cd ~/my-project
consurg init auth-refactor
```

This creates `.consurg.yaml` in your project root with an empty scope named `auth-refactor`.

### 2. Add Files to Tiers

Add the files your agent should be able to modify:

```bash
# Full read-write access (Tier 4 - working_set)
consurg add "src/auth/login.py" "src/auth/session.py" "tests/test_auth.py"
```

Add files the agent can read for context but must not modify:

```bash
# Read-only access (Tier 3 - reference)
consurg add --read "src/core/database.py" "src/core/config.py"
```

Add files where only function/class signatures should be visible:

```bash
# Signature-only access (Tier 2 - signatures)
consurg add --sig "types/auth.pyi"
```

### 3. Check Your Scope

```bash
consurg status
```

Output:

```
         Scope: auth-refactor (ACTIVE)
+--------------+-------+------------------------------------------+
| Tier         | Count | Patterns                                 |
+--------------+-------+------------------------------------------+
| 4 READ-WRITE |     3 | src/auth/login.py, src/auth/session.py,  |
|              |       | tests/test_auth.py                       |
| 3 READ-ONLY  |     2 | src/core/database.py, src/core/config.py |
| 2 SIGNATURE  |     1 | types/auth.pyi                           |
| 1 EXISTENCE  |     0 | -                                        |
+--------------+-------+------------------------------------------+
```

### 4. Visualize the File Tree

```bash
consurg map
```

Shows every file in your project with its tier badge:

```
auth-refactor
[RW] #### src/auth/login.py
[RW] #### src/auth/session.py
[RO] ### src/core/database.py
[RO] ### src/core/config.py
[SIG] ## types/auth.pyi
[--] -- src/utils/helpers.py
[--] -- README.md
```

### 5. Connect to Your AI Tool

Wire Context Surgeon into Claude Code:

```bash
consurg wire claude
```

This generates `.claude/hooks.json` with a PreToolUse hook pointing to the enforcement script.

### 6. Start the Guard

For real-time interactive enforcement:

```bash
consurg guard -i
```

This starts the TUI firewall. In another terminal, use Claude Code normally. Every file access appears in the guard's log. When a blocked file is accessed, you're prompted to approve or deny.

For a simpler one-shot workflow:

```bash
consurg wrap -- claude "fix the login bug"
```

### 7. When You're Done

Deactivate or remove the scope:

```bash
# Deactivate (keeps file, stops enforcement)
consurg off

# Remove entirely
consurg unpin
```

Unwire from your tool:

```bash
consurg wire claude --unwire
```

## Auto-Building Scopes

Instead of manually adding files, let Context Surgeon figure out what belongs:

### From dependency tracing

```bash
consurg trace src/auth/login.py --depth 3 --apply
```

This traces Python/TypeScript imports from `login.py` up to 3 levels deep and automatically classifies files into tiers:
- Entry files go to T4 (working_set)
- Direct dependencies go to T3 (reference)
- Transitive dependencies go to T2 (signatures)

### From git diff

```bash
consurg git-diff main --apply
```

All files changed relative to `main` become T4 (working_set), their direct dependencies become T3 (reference).

## Next Steps

- [Tier Model](tiers.md) -- Understand the 5-tier access model in depth
- [Interactive Guard](guard.md) -- Master the TUI firewall
- [Wire System](wire.md) -- Connect to all supported tools
- [CLI Reference](cli-reference.md) -- Full command reference
