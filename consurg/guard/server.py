"""HTTP server for the guard — receives hook requests and returns decisions.

Runs as a daemon thread. Endpoints:
  POST /evaluate  — evaluate a tool access request
  GET  /health    — liveness check
  GET  /log       — recent access events
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import TYPE_CHECKING

from consurg.constants import PATH_FIELDS, READ_TOOLS, WRITE_TOOLS
from consurg.enforce import resolve_tier

if TYPE_CHECKING:
    from consurg.guard.state import GuardState

# Timeout for interactive approval (8s to stay under Claude Code's 10s limit)
APPROVAL_TIMEOUT = 8.0


class _GuardHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the guard server."""

    state: GuardState  # Set by GuardServer before starting

    def log_message(self, format, *args):
        # Suppress default stderr logging
        pass

    def do_GET(self):
        if self.path == "/health":
            self._respond(200, {"status": "ok", "uptime": self.state.uptime()})
        elif self.path == "/log":
            events = [
                {
                    "timestamp": e.timestamp,
                    "tool": e.tool_name,
                    "file": e.file_path,
                    "tier": e.tier,
                    "label": e.label,
                    "decision": e.decision,
                }
                for e in list(self.state.access_log)[-50:]
            ]
            self._respond(200, {"events": events})
        else:
            self._respond(404, {"error": "not found"})

    def do_POST(self):
        if self.path == "/evaluate":
            self._handle_evaluate()
        else:
            self._respond(404, {"error": "not found"})

    def _handle_evaluate(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            self._respond(400, {"error": "invalid JSON"})
            return

        if not isinstance(data, dict):
            self._respond(400, {"error": "request body must be a JSON object"})
            return

        tool_name = data.get("tool_name", "")
        if not isinstance(tool_name, str):
            self._respond(400, {"error": "tool_name must be a string"})
            return

        file_path = data.get("file_path", "")
        if not isinstance(file_path, str):
            self._respond(400, {"error": "file_path must be a string"})
            return

        tool_input = data.get("tool_input", {})
        if not isinstance(tool_input, dict):
            self._respond(400, {"error": "tool_input must be an object"})
            return

        # If file_path not provided directly, try to extract from tool_input
        if not file_path:
            path_field = PATH_FIELDS.get(tool_name, "")
            if path_field:
                file_path = tool_input.get(path_field, "")
                if not isinstance(file_path, str):
                    self._respond(400, {"error": f"tool_input field '{path_field}' must be a string"})
                    return

        if not file_path:
            self._respond(200, {"decision": "allow", "message": "no file path"})
            return

        tier, label = resolve_tier(file_path, self.state.scope)

        # Determine if this is a write tool
        is_write = tool_name in WRITE_TOOLS

        # Check auto-approved patterns first
        if file_path in self.state.auto_approved:
            approved_tier = self.state.auto_approved[file_path]
            if is_write and approved_tier >= 4:
                self._allow(tool_name, file_path, approved_tier, "READ-WRITE")
                return
            elif not is_write and approved_tier >= 3:
                self._allow(tool_name, file_path, approved_tier, "READ-ONLY")
                return

        # Explorer mode: allow reads
        if self.state.scope.explorer and tool_name in READ_TOOLS:
            self._allow(tool_name, file_path, tier, label)
            return

        # Tier-based decisions
        if tier >= 4:
            self._allow(tool_name, file_path, tier, label)
            return

        if tier >= 2 and not is_write:
            self._allow(tool_name, file_path, tier, label)
            return

        # Access would be denied — check for interactive approval
        if self.state.interactive:
            from consurg.guard.state import ApprovalRequest

            request = ApprovalRequest(
                tool_name=tool_name,
                file_path=file_path,
                tier=tier,
                label=label,
            )
            self.state.set_pending(request)

            # Block until user responds or timeout
            granted = request.event.wait(timeout=APPROVAL_TIMEOUT)
            self.state.clear_pending()

            if granted and request.response and request.response != "d":
                # User approved — promote and allow
                tier_map = {"w": 4, "r": 3, "s": 2}
                promoted_tier = tier_map.get(request.response, 3)
                self.state.promote_file(file_path, promoted_tier)
                tier_labels = {4: "READ-WRITE", 3: "READ-ONLY", 2: "SIGNATURE"}
                new_label = tier_labels.get(promoted_tier, label)
                self._allow(tool_name, file_path, promoted_tier, new_label, promoted=True)
                return

        # Deny
        self._deny(tool_name, file_path, tier, label, is_write)

    def _allow(self, tool_name: str, file_path: str, tier: int, label: str, promoted: bool = False):
        from consurg.guard.state import AccessEvent

        event = AccessEvent(
            timestamp=time.time(),
            tool_name=tool_name,
            file_path=file_path,
            tier=tier,
            label=label,
            decision="allow",
            promoted=promoted,
        )
        self.state.add_event(event)
        self._respond(200, {"decision": "allow", "tier": tier, "label": label})

    def _deny(self, tool_name: str, file_path: str, tier: int, label: str, is_write: bool):
        from consurg.guard.state import AccessEvent

        reason = "write blocked" if is_write and tier >= 2 else "access denied"
        event = AccessEvent(
            timestamp=time.time(),
            tool_name=tool_name,
            file_path=file_path,
            tier=tier,
            label=label,
            decision="deny",
        )
        self.state.add_event(event)
        self._respond(200, {
            "decision": "deny",
            "tier": tier,
            "label": label,
            "message": f"[CONTEXT SURGEON] {reason}: {file_path} (Tier {tier} {label})",
        })

    def _respond(self, status: int, body: dict):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())


class GuardServer:
    """Wraps HTTPServer to run in a daemon thread."""

    def __init__(self, state: GuardState):
        self.state = state
        _GuardHandler.state = state
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._server = HTTPServer(("127.0.0.1", self.state.port), _GuardHandler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server = None
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()
