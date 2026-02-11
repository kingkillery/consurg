"""Context Surgeon - Wire system for auto-configuring tool hooks."""

from consurg.wire.base import BaseWirer
from consurg.wire.claude import ClaudeWirer
from consurg.wire.codex import CodexWirer
from consurg.wire.droid import DroidWirer
from consurg.wire.gemini import GeminiWirer
from consurg.wire.pk_agent import PkAgentWirer

WIRERS: dict[str, type[BaseWirer]] = {
    "claude": ClaudeWirer,
    "pk-agent": PkAgentWirer,
    "droid": DroidWirer,
    "gemini": GeminiWirer,
    "codex": CodexWirer,
}

__all__ = [
    "BaseWirer",
    "ClaudeWirer",
    "PkAgentWirer",
    "DroidWirer",
    "GeminiWirer",
    "CodexWirer",
    "WIRERS",
]
