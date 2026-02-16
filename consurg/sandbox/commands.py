"""Classify shell commands against tier capabilities and deny lists."""

from __future__ import annotations

import shlex
from dataclasses import dataclass

from consurg.scope import Scope

# Tier-to-command capability matrix.
# Each tier maps to a set of allowed command base names.
# None means "all commands allowed" (T4).
TIER_COMMAND_CAPABILITIES: dict[int, set[str] | None] = {
    0: set(),  # T0: no execution
    1: {"ls", "stat", "file", "wc", "du", "df"},  # T1: existence inspection
    2: {  # T2: interface inspection + T1
        "ls", "stat", "file", "wc", "du", "df",
        "python --version", "node --version", "git --version",
        "type", "which", "where", "mypy", "pyright", "tsc",
    },
    3: {  # T3: non-destructive read ops + T2
        "ls", "stat", "file", "wc", "du", "df",
        "python --version", "node --version", "git --version",
        "type", "which", "where", "mypy", "pyright", "tsc",
        "cat", "head", "tail", "less", "more",
        "grep", "rg", "find", "fd", "ag",
        "git diff", "git log", "git status", "git show", "git branch",
        "pytest", "python -m pytest", "npm test", "cargo test",
        "echo", "printf", "date", "env", "printenv",
    },
    4: None,  # T4: all commands allowed (within workspace)
}

# Shell metacharacters that indicate command chaining/injection.
_SHELL_META = {"|", ";", "&&", "||", "`"}
_SHELL_SUBST = {"$(", "${"}


@dataclass
class CommandDecision:
    allow: bool
    reason: str
    tier: int


def _extract_base_command(cmd: str) -> str:
    """Extract the first token (base command name) from a command string."""
    try:
        tokens = shlex.split(cmd)
    except ValueError:
        return cmd.strip().split()[0] if cmd.strip() else ""
    return tokens[0] if tokens else ""


def _has_shell_metacharacters(cmd: str) -> bool:
    """Check if the command contains shell chaining/injection metacharacters."""
    for meta in _SHELL_META:
        if meta in cmd:
            return True
    for subst in _SHELL_SUBST:
        if subst in cmd:
            return True
    if "`" in cmd:
        return True
    return False


def _matches_deny_list(cmd: str, deny_list: list[str]) -> str | None:
    """Check if command matches any entry in the deny list. Returns matched entry or None."""
    cmd_stripped = cmd.strip()
    for entry in deny_list:
        entry_stripped = entry.strip()
        if cmd_stripped == entry_stripped:
            return entry
        if cmd_stripped.startswith(entry_stripped):
            return entry
    return None


def _command_in_tier_set(cmd: str, allowed: set[str]) -> bool:
    """Check if a command (or its base name) is in the allowed set for a tier."""
    base = _extract_base_command(cmd)
    if base in allowed:
        return True
    # Check two-token commands like "git diff", "python -m"
    try:
        tokens = shlex.split(cmd)
    except ValueError:
        return False
    if len(tokens) >= 2:
        two_token = f"{tokens[0]} {tokens[1]}"
        if two_token in allowed:
            return True
    return False


def classify_command(
    cmd: str, tier: int, scope: Scope
) -> CommandDecision:
    """Classify whether a command is allowed at the given tier.

    Decision order:
    1. Explicit deny list (always deny, regardless of tier)
    2. Shell metacharacters at low autonomy (deny at autonomy 0-1)
    3. Tier capability matrix
    """
    if not cmd or not cmd.strip():
        return CommandDecision(allow=False, reason="empty command", tier=tier)

    # 1. Check explicit deny list from scope
    deny_match = _matches_deny_list(cmd, scope.sandbox.command_deny)
    if deny_match is not None:
        return CommandDecision(
            allow=False,
            reason=f"command matches deny list entry: {deny_match!r}",
            tier=tier,
        )

    # 2. Shell metacharacters at low autonomy
    autonomy = scope.sandbox.autonomy
    if _has_shell_metacharacters(cmd) and autonomy <= 1:
        return CommandDecision(
            allow=False,
            reason=f"shell metacharacters not allowed at autonomy={autonomy}",
            tier=tier,
        )

    # 3. Tier capability matrix
    allowed = TIER_COMMAND_CAPABILITIES.get(tier)

    # T4 (None) means all commands allowed
    if allowed is None:
        return CommandDecision(allow=True, reason="tier 4: full execution", tier=tier)

    # T0 empty set means nothing allowed
    if not allowed:
        return CommandDecision(
            allow=False, reason=f"tier {tier}: no command execution", tier=tier
        )

    # Check against allowed set
    if _command_in_tier_set(cmd, allowed):
        return CommandDecision(
            allow=True, reason=f"tier {tier}: command allowed", tier=tier
        )

    return CommandDecision(
        allow=False,
        reason=f"tier {tier}: command not in allowed set",
        tier=tier,
    )
