#!/usr/bin/env python3
"""
Multi-agent scope narrowing example.

Demonstrates how to create child scopes for subagents from a parent scope.
Child scopes enforce monotonic narrowing: a subagent can see less than its
parent, never more. Files inherit their parent tier and cannot be promoted.

Use cases:
  - Assigning focused subtasks to sub-agents
  - Preventing a code-review agent from accessing unrelated modules
  - Splitting a large task across specialized agents without overlap
"""
from pathlib import Path

from consurg.scope import Scope, narrow_scope, detect_write_conflicts


def main():
    # Parent scope: full auth module with broad reference access
    parent = Scope(
        version=1,
        scope_name="auth-refactor",
        active=True,
        reason="Full auth module refactor",
        working_set=[
            "src/auth/login.py",
            "src/auth/register.py",
            "src/auth/session.py",
        ],
        reference=[
            "src/core/database.py",
            "src/core/config.py",
        ],
        signatures=["types/auth.pyi"],
        visible=["pyproject.toml"],
        dynamic_deps=[],
        explorer=False,
    )

    # --- Narrow for Agent A: login-focused subagent ---
    agent_a_scope = narrow_scope(
        parent,
        [
            "src/auth/login.py",       # Inherits T4 from parent
            "src/core/database.py",    # Inherits T3 from parent
        ],
    )
    # Child scopes auto-name as "parent/child". Set distinct names if needed:
    agent_a_scope.scope_name = "auth-refactor/agent-a-login"

    print(f"Agent A working_set: {agent_a_scope.working_set}")
    print(f"Agent A reference:   {agent_a_scope.reference}")
    # Agent A gets: login.py (T4), database.py (T3)
    # Agent A CANNOT see: register.py, session.py, config.py

    # --- Narrow for Agent B: registration-focused subagent ---
    agent_b_scope = narrow_scope(
        parent,
        [
            "src/auth/register.py",    # Inherits T4 from parent
            "src/core/config.py",      # Inherits T3 from parent
        ],
    )
    agent_b_scope.scope_name = "auth-refactor/agent-b-register"

    print(f"\nAgent B working_set: {agent_b_scope.working_set}")
    print(f"Agent B reference:   {agent_b_scope.reference}")

    # --- Check for write conflicts between agents ---
    conflicts = detect_write_conflicts([agent_a_scope, agent_b_scope])
    if conflicts:
        print(f"\nWrite conflicts detected: {conflicts}")
    else:
        print("\nNo write conflicts -- agents can run in parallel safely")

    # --- Attempting to include a blocked file raises ScopeError ---
    try:
        bad_scope = narrow_scope(parent, ["src/unrelated/module.py"])
    except Exception as e:
        print(f"\nExpected error for blocked file: {e}")


if __name__ == "__main__":
    main()
