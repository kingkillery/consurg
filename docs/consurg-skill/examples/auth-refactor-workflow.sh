#!/usr/bin/env bash
# End-to-end auth refactor workflow with Context Surgeon
# Demonstrates manual scope creation, wiring, guard, and cleanup

set -euo pipefail

PROJECT_DIR="${1:-.}"
cd "$PROJECT_DIR"

echo "=== Step 1: Initialize scope ==="
consurg init auth-refactor

echo "=== Step 2: Add files to tiers ==="
# Working set (T4) - files the agent will modify
consurg add "src/auth/*.py" "tests/test_auth.py"

# Reference (T3) - context files, read-only
consurg add --read "src/core/database.py" "src/core/config.py" "docs/auth.md"

# Signatures (T2) - type stubs for API contracts
consurg add --sig "types/auth.pyi"

echo "=== Step 3: Activate enforcement ==="
consurg on

echo "=== Step 4: Check scope ==="
consurg status
consurg map

echo "=== Step 5: Wire to Claude Code ==="
consurg wire claude

echo "=== Step 6: Run with enforcement ==="
# Option A: Interactive guard (run in a separate terminal)
# consurg guard -i

# Option B: Wrapped one-shot (headless, auto-cleanup)
consurg wrap -- claude "Fix the authentication bug in src/auth/login.py"

echo "=== Step 7: Cleanup ==="
consurg off
consurg wire claude --unwire

echo "=== Done ==="
