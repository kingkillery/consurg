#!/usr/bin/env python3
"""
Interactive quick-scope setup helper.

Cross-platform: runs on Windows (CMD, PowerShell), macOS, and Linux.
Uses only Python stdlib + consurg CLI (no bash/shell dependencies).

Prompts for scope name, files per tier, then runs consurg commands
to initialize and populate the scope.

Usage:
  python quick_scope.py                    # Interactive mode in cwd
  python quick_scope.py auth-fix           # Pre-set scope name
  python quick_scope.py --non-interactive  # Fail if stdin is not a terminal

Exit codes:
  0 - Scope created successfully
  1 - Error or user abort
  2 - consurg not found
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path


def find_consurg() -> list[str]:
    """Find the consurg command. Returns the command prefix as a list."""
    # Try bare 'consurg' first
    if shutil.which("consurg"):
        return ["consurg"]

    # Try 'python -m consurg'
    python = sys.executable or "python"
    try:
        result = subprocess.run(
            [python, "-m", "consurg", "--help"],
            capture_output=True, timeout=10,
        )
        if result.returncode == 0:
            return [python, "-m", "consurg"]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    return []


def run_consurg(cmd_prefix: list[str], args: list[str], cwd: str | None = None) -> bool:
    """Run a consurg command. Returns True on success."""
    full_cmd = cmd_prefix + args
    try:
        result = subprocess.run(
            full_cmd,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=cwd,
        )
        if result.stdout.strip():
            print(result.stdout.strip())
        if result.returncode != 0 and result.stderr.strip():
            print(f"  Error: {result.stderr.strip()}", file=sys.stderr)
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        print(f"  Error: Command timed out: {' '.join(full_cmd)}", file=sys.stderr)
        return False
    except FileNotFoundError:
        print(f"  Error: Command not found: {full_cmd[0]}", file=sys.stderr)
        return False


def prompt(message: str, default: str = "") -> str:
    """Prompt user for input with optional default."""
    suffix = f" [{default}]" if default else ""
    try:
        value = input(f"{message}{suffix}: ").strip()
        return value if value else default
    except (EOFError, KeyboardInterrupt):
        print("\nAborted.")
        sys.exit(1)


def prompt_yn(message: str, default: bool = True) -> bool:
    """Prompt for yes/no."""
    suffix = " [Y/n]" if default else " [y/N]"
    try:
        value = input(f"{message}{suffix}: ").strip().lower()
        if not value:
            return default
        return value in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        print("\nAborted.")
        sys.exit(1)


def prompt_patterns(tier_name: str, tier_desc: str, examples: str) -> str:
    """Prompt for file patterns for a tier."""
    print(f"\n--- {tier_name} ({tier_desc}) ---")
    print(f"Enter file patterns (space-separated, empty to skip)")
    print(f"Examples: {examples}")
    return prompt(">")


def main():
    args = sys.argv[1:]
    non_interactive = "--non-interactive" in args
    args = [a for a in args if a != "--non-interactive"]

    # Check terminal
    if non_interactive and not sys.stdin.isatty():
        print("Error: --non-interactive requires a terminal for input", file=sys.stderr)
        sys.exit(1)

    # Find consurg
    cmd = find_consurg()
    if not cmd:
        print("Error: consurg not found.", file=sys.stderr)
        print("Install with: pip install -e /path/to/consurg", file=sys.stderr)
        sys.exit(2)

    print(f"Using: {' '.join(cmd)}")

    # Check for existing scope
    scope_file = Path(".consurg.yaml")
    if scope_file.exists():
        print(f"\nScope already exists: {scope_file}")
        run_consurg(cmd, ["status"])
        if not prompt_yn("\nOverwrite?", default=False):
            print("Aborted.")
            sys.exit(0)
        try:
            scope_file.unlink()
        except PermissionError:
            print(f"Error: Cannot delete {scope_file} (permission denied)", file=sys.stderr)
            sys.exit(1)

    # Get scope name
    scope_name = args[0] if args else ""
    if not scope_name:
        default_name = Path.cwd().name
        scope_name = prompt("Scope name (e.g., auth-fix, schema-refactor)", default=default_name)

    if not scope_name:
        print("Error: Scope name is required", file=sys.stderr)
        sys.exit(1)

    # Initialize
    print(f"\nInitializing scope: {scope_name}")
    if not run_consurg(cmd, ["init", scope_name]):
        print("Error: Failed to initialize scope", file=sys.stderr)
        sys.exit(1)

    # Tier 4: Working set
    working = prompt_patterns(
        "Working Set", "T4: read-write",
        "src/auth/*.py tests/test_auth.py"
    )
    if working:
        patterns = working.split()
        if not run_consurg(cmd, ["add"] + patterns):
            print("Warning: Some patterns may not have been added", file=sys.stderr)

    # Tier 3: Reference
    reference = prompt_patterns(
        "Reference", "T3: read-only",
        "src/core/*.py docs/*.md pyproject.toml"
    )
    if reference:
        patterns = reference.split()
        if not run_consurg(cmd, ["add", "--read"] + patterns):
            print("Warning: Some patterns may not have been added", file=sys.stderr)

    # Tier 2: Signatures
    sigs = prompt_patterns(
        "Signatures", "T2: headers only",
        "types/*.pyi src/interfaces/*.ts"
    )
    if sigs:
        patterns = sigs.split()
        if not run_consurg(cmd, ["add", "--sig"] + patterns):
            print("Warning: Some patterns may not have been added", file=sys.stderr)

    # Tier 1: Visible (manual YAML edit required)
    # The consurg CLI has --read (T3) and --sig (T2) flags but no --vis flag for T1.
    # This is by design — T1 (existence-only) is rarely needed interactively, so we
    # handle it by editing .consurg.yaml directly rather than adding a CLI flag.
    visible = prompt_patterns(
        "Visible",
        "T1: existence only (the agent can see filenames but cannot read contents)",
        "config.yaml .env.example"
    )
    if visible:
        patterns = visible.split()
        print(f"  Note: Tier 1 requires manual .consurg.yaml edit (no CLI flag).")
        try:
            import yaml

            data = yaml.safe_load(scope_file.read_text(encoding="utf-8"))
            if data.get("visible") is None:
                data["visible"] = []
            data["visible"].extend(patterns)
            scope_file.write_text(yaml.dump(data, default_flow_style=False), encoding="utf-8")
            print(f"  Added {len(patterns)} pattern(s) to visible tier")
        except ImportError:
            print("  Warning: PyYAML not available. Edit .consurg.yaml manually to add visible patterns.")
        except Exception as e:
            print(f"  Warning: Could not update .consurg.yaml: {e}")

    # Activate
    run_consurg(cmd, ["on"])

    # Show result
    print("\n" + "=" * 40)
    print("Scope Created")
    print("=" * 40)
    run_consurg(cmd, ["status"])

    # Next steps
    print("\nNext steps:")
    print("  consurg wire claude        # Wire to Claude Code")
    print("  consurg wire codex         # Wire to Codex CLI")
    print("  consurg guard -i           # Start interactive guard")
    print("  consurg wrap -- CMD ARGS   # Run with enforcement")


if __name__ == "__main__":
    main()
