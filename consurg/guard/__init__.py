"""Context Surgeon - Interactive Guard (real-time scope firewall)."""

from consurg.guard.lockfile import GuardLockfile
from consurg.guard.server import GuardServer
from consurg.guard.state import AccessEvent, ApprovalRequest, GuardState

__all__ = [
    "GuardState",
    "AccessEvent",
    "ApprovalRequest",
    "GuardServer",
    "GuardLockfile",
]
