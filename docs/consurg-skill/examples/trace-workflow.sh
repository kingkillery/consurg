#!/usr/bin/env bash
# Auto-scope workflow using dependency tracing
# Demonstrates building a scope from import analysis

set -euo pipefail

PROJECT_DIR="${1:-.}"
cd "$PROJECT_DIR"

echo "=== Step 1: Trace dependencies from entry point ==="
# Traces Python/TypeScript imports up to 3 levels deep
# Entry file -> T4, direct deps -> T3, transitive deps -> T2
consurg trace src/auth/login.py --depth 3 --apply

echo "=== Step 2: Review what was generated ==="
consurg status
consurg map

echo "=== Step 3: Refine if needed ==="
# Add extra reference files the tracer missed
consurg add --read "docs/auth-spec.md"
# Remove files that don't belong
# consurg remove "src/unrelated/module.py"

echo "=== Step 4: Wire and run ==="
consurg wire claude
consurg wrap -- claude "Refactor the authentication flow"

echo "=== Cleanup ==="
consurg off
consurg wire claude --unwire

# --- ALTERNATIVE WORKFLOW: Git Diff Scoping ---
# The workflow below is a self-contained alternative to the trace workflow above.
# Each workflow is independent — run one or the other, not both in sequence.
# If switching between workflows, run cleanup (consurg off && consurg wire claude --unwire) first.

echo "---"
echo "Alternative: Build scope from git diff"
echo "---"

# Build scope from what changed on this branch vs main
consurg git-diff main --apply
consurg status

# Changed files -> T4, their deps -> T3
# Great for PR-scoped agent sessions
