#!/usr/bin/env python3
"""
Validate a .consurg.yaml scope file.

Cross-platform: runs on Windows (CMD, PowerShell), macOS, and Linux.

Checks:
  - File exists and is valid YAML
  - Required fields present (version, scope, active)
  - Version is 1
  - Field types are correct (active: bool, reason: str, explorer: bool)
  - Tier lists contain only non-empty strings
  - Patterns are valid fnmatch patterns
  - No duplicate patterns within or across tiers
  - Pattern matching sanity (warns on suspicious patterns)

Usage:
  python validate_scope.py                      # Validates .consurg.yaml in cwd
  python validate_scope.py /path/to/scope.yaml  # Validates specific file
  python validate_scope.py --strict             # Treat warnings as errors

Exit codes:
  0 - Valid (no errors)
  1 - Invalid (errors found)
  2 - File not found or unreadable
"""
import sys
from fnmatch import fnmatch
from pathlib import Path

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML is required. Install with: pip install pyyaml", file=sys.stderr)
    sys.exit(2)


def validate(path: Path, strict: bool = False) -> tuple[list[str], list[str]]:
    """Validate scope file. Returns (errors, warnings)."""
    errors: list[str] = []
    warnings: list[str] = []

    # --- File existence and readability ---
    if not path.exists():
        return [f"File not found: {path}"], []

    if not path.is_file():
        return [f"Not a file: {path}"], []

    try:
        raw = path.read_text(encoding="utf-8")
    except PermissionError:
        return [f"Permission denied: {path}"], []
    except UnicodeDecodeError:
        return [f"File is not valid UTF-8: {path}"], []

    if not raw.strip():
        return ["File is empty"], []

    # --- YAML parsing ---
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        return [f"Invalid YAML: {e}"], []

    if not isinstance(data, dict):
        return ["Root element must be a YAML mapping (key: value pairs)"], []

    # --- Required fields ---
    required = {"version": int, "scope": str, "active": bool}
    for field, expected_type in required.items():
        if field not in data:
            errors.append(f"Missing required field: '{field}'")
        elif not isinstance(data[field], expected_type):
            actual = type(data[field]).__name__
            errors.append(
                f"'{field}' must be {expected_type.__name__}, got {actual}: {data[field]!r}"
            )

    # --- Version check ---
    if "version" in data and isinstance(data["version"], int):
        if data["version"] != 1:
            errors.append(f"Unsupported version: {data['version']} (only version 1 is supported)")

    # --- Optional field types ---
    optional_str = {"reason": str}
    optional_bool = {"explorer": bool}

    for field, expected_type in optional_str.items():
        if field in data and data[field] is not None and not isinstance(data[field], expected_type):
            actual = type(data[field]).__name__
            errors.append(f"'{field}' must be {expected_type.__name__}, got {actual}")

    for field, expected_type in optional_bool.items():
        if field in data and data[field] is not None and not isinstance(data[field], expected_type):
            actual = type(data[field]).__name__
            errors.append(f"'{field}' must be {expected_type.__name__}, got {actual}")

    # --- Tier list validation ---
    tier_keys = {
        "working_set": "T4 READ-WRITE",
        "reference": "T3 READ-ONLY",
        "signatures": "T2 SIGNATURE",
        "visible": "T1 EXISTENCE",
        "dynamic_deps": "dynamic dependencies",
    }

    all_patterns: dict[str, str] = {}  # pattern -> first tier it appeared in

    for key, tier_label in tier_keys.items():
        value = data.get(key)

        if value is None:
            continue  # absent or explicitly null

        if not isinstance(value, list):
            errors.append(f"'{key}' must be a list, got {type(value).__name__}")
            continue

        for i, pattern in enumerate(value):
            loc = f"{key}[{i}]"

            # Type check
            if not isinstance(pattern, str):
                errors.append(f"{loc} must be a string, got {type(pattern).__name__}: {pattern!r}")
                continue

            # Empty check
            stripped = pattern.strip()
            if not stripped:
                errors.append(f"{loc} is empty or whitespace-only")
                continue

            if stripped != pattern:
                warnings.append(f"{loc} has leading/trailing whitespace: {pattern!r}")

            # Duplicate check (across tiers)
            if pattern in all_patterns:
                errors.append(
                    f"Duplicate pattern '{pattern}' in '{key}' "
                    f"(already in '{all_patterns[pattern]}')"
                )
            else:
                all_patterns[pattern] = key

            # fnmatch validity
            try:
                fnmatch("test.py", pattern)
            except Exception as e:
                errors.append(f"{loc} invalid pattern '{pattern}': {e}")

            # Suspicious pattern warnings
            if "\\" in pattern:
                warnings.append(
                    f"{loc} contains backslash: '{pattern}'. "
                    "Use forward slashes (/) for path separators, even on Windows."
                )

            if pattern.startswith("/") or (len(pattern) > 1 and pattern[1] == ":"):
                warnings.append(
                    f"{loc} looks like an absolute path: '{pattern}'. "
                    "Patterns should be relative to the project root."
                )

            if "**" in pattern:
                warnings.append(
                    f"{loc} uses '**' glob: '{pattern}'. "
                    "fnmatch does not support recursive '**'. Use single '*' per directory level."
                )

    # --- Unknown keys ---
    known_keys = {
        "version", "scope", "active", "reason",
        "working_set", "reference", "signatures", "visible",
        "dynamic_deps", "explorer",
    }
    for key in data:
        if key not in known_keys:
            warnings.append(f"Unknown field: '{key}' (will be ignored by consurg)")

    return errors, warnings


def main():
    # Parse args (no external dependency)
    args = sys.argv[1:]
    strict = "--strict" in args
    args = [a for a in args if a != "--strict"]

    path = Path(args[0]) if args else Path(".consurg.yaml")

    # Resolve relative paths
    path = path.resolve()

    errors, warnings = validate(path, strict=strict)

    # Display results
    if strict:
        errors.extend(warnings)
        warnings = []

    if errors:
        print(f"INVALID: {path}")
        for err in errors:
            print(f"  ERROR: {err}")
        for warn in warnings:
            print(f"  WARN:  {warn}")
        sys.exit(1)

    # Valid - show summary
    print(f"VALID: {path}")
    for warn in warnings:
        print(f"  WARN:  {warn}")

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        tiers = {
            "working_set (T4)": len(data.get("working_set") or []),
            "reference (T3)": len(data.get("reference") or []),
            "signatures (T2)": len(data.get("signatures") or []),
            "visible (T1)": len(data.get("visible") or []),
        }
        total = sum(tiers.values())
        active = "ACTIVE" if data.get("active") else "INACTIVE"
        explorer = " [EXPLORER]" if data.get("explorer") else ""
        print(f"  Scope: {data.get('scope', '?')} ({active}{explorer})")
        print(f"  Patterns: {total} total")
        for name, count in tiers.items():
            if count > 0:
                print(f"    {name}: {count}")
    except Exception:
        pass  # Summary is best-effort

    sys.exit(0)


if __name__ == "__main__":
    main()
