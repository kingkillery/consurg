"""Thread-safe shared state for the guard server and TUI."""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field

from consurg.scope import Scope


@dataclass
class AccessEvent:
    timestamp: float
    tool_name: str
    file_path: str
    tier: int
    label: str
    decision: str  # "allow" or "deny"
    promoted: bool = False  # True if user promoted tier during this request
    request_type: str = "file"  # "file" | "command" | "network"
    command: str = ""  # populated when request_type == "command"
    hostname: str = ""  # populated when request_type == "network"


@dataclass
class ApprovalRequest:
    """A pending interactive approval waiting for user input."""

    tool_name: str
    file_path: str
    tier: int
    label: str
    event: threading.Event = field(default_factory=threading.Event)
    response: str | None = None  # "w", "r", "s", "d" or None (timeout)
    promoted_tier: int | None = None


class GuardState:
    """Thread-safe shared state between server, TUI, and keyboard threads."""

    def __init__(self, scope: Scope, interactive: bool = True, port: int = 9876):
        self.scope = scope
        self.interactive = interactive
        self.port = port
        self.access_log: deque[AccessEvent] = deque(maxlen=500)
        self.pending: ApprovalRequest | None = None
        self.auto_approved: dict[str, int] = {}  # pattern -> tier
        self.lock = threading.Lock()
        self.running = True
        self.start_time = time.time()

    def add_event(self, event: AccessEvent) -> None:
        with self.lock:
            self.access_log.append(event)

    def set_pending(self, request: ApprovalRequest) -> None:
        with self.lock:
            self.pending = request

    def clear_pending(self) -> None:
        with self.lock:
            self.pending = None

    def get_pending(self) -> ApprovalRequest | None:
        with self.lock:
            return self.pending

    def promote_file(self, file_path: str, tier: int) -> None:
        """Promote a file to a higher tier in the live scope."""
        with self.lock:
            if tier >= 4:
                if file_path not in self.scope.working_set:
                    self.scope.working_set.append(file_path)
            elif tier >= 3:
                if file_path not in self.scope.reference:
                    self.scope.reference.append(file_path)
            elif tier >= 2:
                if file_path not in self.scope.signatures:
                    self.scope.signatures.append(file_path)
            self.auto_approved[file_path] = tier

    def tier_counts(self) -> dict[int, int]:
        with self.lock:
            return {
                4: len(self.scope.working_set),
                3: len(self.scope.reference),
                2: len(self.scope.signatures),
                1: len(self.scope.visible),
            }

    def uptime(self) -> float:
        return time.time() - self.start_time
