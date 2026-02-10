# Ralph Agent Instructions

## Your Task

1. Read `scripts/ralph/prd.json`.
2. Read `scripts/ralph/progress.txt` (check **Codebase Patterns** first).
3. Ensure you are on the branch specified in `prd.json` (`branchName`). Create it if it does not exist.
4. Pick the highest priority story where `passes: false`.
5. Implement that ONE story.
6. Run checks:
   - `python -m pytest tests/ -v` (run all tests)
   - `python -m consurg --help` (verify CLI loads)
7. Append learnings to `scripts/ralph/progress.txt`.
8. Commit with message: `feat: [ID] - [Title]`.
9. Update `scripts/ralph/prd.json`: set `passes: true` for that story.

## Project Context

This is **Context Surgeon** - a Python library and CLI for temporarily restricting AI coding agents to a declared subset of files.

Key references:
- `prd.md` - Full product requirements document
- `context-surgeon.md` - Concept document with design rationale

## Technical Constraints

- Python 3.10+ (currently 3.14 available)
- Dependencies: typer, rich, pyyaml (all installed)
- Package name: `consurg`
- CLI entry point: `python -m consurg` (via typer)
- Hook entry point: `hooks/enforce.py` (reads stdin JSON, signals via exit code)
- Plugin structure: `.claude-plugin/plugin.json` at project root

## Architecture

```
consurg/                    # Python package
  __init__.py
  cli.py                   # Typer CLI app
  scope.py                 # Scope loading, validation, Scope dataclass
  enforce.py               # Tier resolution logic (resolve_tier)
hooks/
  enforce.py               # Hook entry point (stdin JSON -> exit code)
  hooks.json               # Claude Code hook config
.claude-plugin/
  plugin.json              # Plugin manifest
commands/
  scope.md                 # /scope slash command
tests/
  test_scope.py
  test_enforce.py
  test_hook.py
  test_integration.py
pyproject.toml
```

## Coding Standards

- Use dataclasses for Scope model (not pydantic - keep deps minimal)
- Use fnmatch for glob pattern matching against file paths
- Use pathlib.Path throughout (no os.path)
- Hook enforce.py must add project root to sys.path to import from consurg package
- All tests use tmp_path fixture for isolation
- No docstrings on obvious functions. Comments only where logic is non-obvious.

## Progress Format

APPEND to `scripts/ralph/progress.txt`:

## [YYYY-MM-DD] - [Story ID]
- What was implemented
- Files changed
- **Learnings:**
  - Patterns discovered
  - Gotchas encountered
---

## Codebase Patterns

If you discover reusable patterns, add them to the TOP of `scripts/ralph/progress.txt` under `## Codebase Patterns`.

## Stop Condition

If ALL stories pass, reply with:

<promise>COMPLETE</promise>
