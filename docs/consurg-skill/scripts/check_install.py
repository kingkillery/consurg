#!/usr/bin/env python3
"""
Verify Context Surgeon installation and environment.

Cross-platform: runs on Windows (CMD, PowerShell), macOS, and Linux.
Uses only Python stdlib for the runner; tests consurg imports.

Checks:
  - Python version (3.10+)
  - consurg CLI availability
  - Runtime dependencies (typer, rich, pyyaml)
  - All consurg submodules importable
  - Test framework available (optional)

Usage:
  python check_install.py          # Standard check
  python check_install.py --fix    # Show install commands for failures

Exit codes:
  0 - All checks passed
  1 - One or more checks failed
"""
import importlib
import shutil
import subprocess
import sys
from pathlib import Path


class CheckResult:
    def __init__(self):
        self.passed: list[str] = []
        self.failed: list[str] = []
        self.warnings: list[str] = []

    def check(self, label: str, condition: bool, fix_hint: str = ""):
        if condition:
            self.passed.append(label)
            print(f"  [PASS] {label}")
        else:
            self.failed.append(label)
            msg = f"  [FAIL] {label}"
            if fix_hint:
                msg += f"  -- {fix_hint}"
            print(msg)

    def warn(self, label: str, message: str):
        self.warnings.append(f"{label}: {message}")
        print(f"  [WARN] {label}: {message}")


def try_import(module: str) -> bool:
    """Try to import a module. Returns True if successful."""
    try:
        importlib.import_module(module)
        return True
    except ImportError:
        return False
    except Exception:
        return False


def try_from_import(module: str, name: str) -> bool:
    """Try 'from module import name'. Returns True if successful."""
    try:
        mod = importlib.import_module(module)
        return hasattr(mod, name)
    except ImportError:
        return False
    except Exception:
        return False


def check_cli_available() -> bool:
    """Check if consurg CLI is available."""
    # Try bare command
    if shutil.which("consurg"):
        return True

    # Try python -m consurg
    python = sys.executable or "python"
    try:
        result = subprocess.run(
            [python, "-m", "consurg", "--help"],
            capture_output=True, timeout=10,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def main():
    show_fix = "--fix" in sys.argv

    print("=" * 50)
    print("Context Surgeon Installation Check")
    print("=" * 50)

    r = CheckResult()

    # --- Python version ---
    print(f"\nPython: {sys.version}")
    print(f"Platform: {sys.platform}")
    print(f"Executable: {sys.executable}")
    print()

    vi = sys.version_info
    r.check(
        f"Python >= 3.10 (found {vi.major}.{vi.minor}.{vi.micro})",
        vi >= (3, 10),
        fix_hint="Install Python 3.10+ from https://python.org",
    )

    # --- CLI availability ---
    print()
    cli_ok = check_cli_available()
    cli_hint = "pip install -e /path/to/consurg" if show_fix else ""
    r.check("consurg CLI available", cli_ok, fix_hint=cli_hint)

    if cli_ok:
        # Check --help works
        python = sys.executable or "python"
        try:
            result = subprocess.run(
                [python, "-m", "consurg", "--help"],
                capture_output=True, text=True, timeout=10,
            )
            r.check("consurg --help executes", result.returncode == 0)
        except Exception:
            r.check("consurg --help executes", False)

    # --- Runtime dependencies ---
    print()
    deps = {
        "typer": "pip install typer>=0.9.0",
        "rich": "pip install rich>=13.0.0",
        "yaml": "pip install pyyaml>=6.0",
    }
    for mod, fix in deps.items():
        hint = fix if show_fix else ""
        r.check(f"Dependency: {mod}", try_import(mod), fix_hint=hint)

    # --- consurg package ---
    print()
    r.check("consurg package importable", try_import("consurg"))

    # Core modules
    core_imports = [
        ("consurg.enforce", "resolve_tier"),
        ("consurg.scope", "load_scope"),
        ("consurg.scope", "Scope"),
        ("consurg.scope", "ScopeError"),
        ("consurg.scope", "narrow_scope"),
        ("consurg.scope", "detect_write_conflicts"),
    ]
    for mod, name in core_imports:
        r.check(f"Import: from {mod} import {name}", try_from_import(mod, name))

    # Subpackages
    subpackages = [
        ("consurg.trace", "DependencyGraph"),
        ("consurg.trace", "resolve_python_imports"),
        ("consurg.trace", "resolve_ts_imports"),
        ("consurg.trace", "extract_signatures"),
        ("consurg.adapters", "generate_claude_scope"),
        ("consurg.adapters", "generate_cursor_rules"),
        ("consurg.adapters", "generate_aider_args"),
        ("consurg.adapters", "generate_generic_prompt"),
        ("consurg.guard", "GuardState"),
        ("consurg.wire", "WIRERS"),
    ]
    for mod, name in subpackages:
        r.check(f"Import: from {mod} import {name}", try_from_import(mod, name))

    # --- Dev dependencies (optional) ---
    print()
    pytest_ok = try_import("pytest")
    if pytest_ok:
        r.check("Dev dependency: pytest", True)
    else:
        r.warn("pytest", "Not installed. Install with: pip install -e '.[dev]'")

    # --- Summary ---
    print()
    print("=" * 50)
    total = len(r.passed) + len(r.failed)
    print(f"Results: {len(r.passed)}/{total} passed, {len(r.failed)} failed")
    if r.warnings:
        print(f"Warnings: {len(r.warnings)}")
    print("=" * 50)

    if r.failed:
        print()
        if show_fix:
            print("Fix all failures with:")
            print("  pip install -e /path/to/consurg")
            print("  pip install -e '/path/to/consurg[dev]'")
        else:
            print("Run with --fix to see install commands for each failure.")
        sys.exit(1)
    else:
        print("\nAll checks passed.")
        sys.exit(0)


if __name__ == "__main__":
    main()
