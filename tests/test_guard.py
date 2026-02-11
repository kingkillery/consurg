"""Tests for the guard server, state, and lockfile."""

import json
import os
import tempfile
import threading
import time
import urllib.request
import urllib.error
from pathlib import Path
from unittest.mock import patch

import pytest

from consurg.guard.lockfile import GuardLockfile
from consurg.guard.server import GuardServer
from consurg.guard.state import AccessEvent, ApprovalRequest, GuardState
from consurg.scope import Scope


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def scope():
    return Scope(
        scope_name="test-scope",
        active=True,
        working_set=["src/auth.py", "src/auth/*.py"],
        reference=["src/core.py", "docs/*.md"],
        signatures=["types/*.pyi"],
        visible=["config.yaml"],
    )


@pytest.fixture
def state(scope):
    return GuardState(scope=scope, interactive=False, port=0)


@pytest.fixture
def interactive_state(scope):
    return GuardState(scope=scope, interactive=True, port=0)


@pytest.fixture
def server(state):
    """Start a guard server on a random port and yield the state."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    state.port = port
    srv = GuardServer(state)
    srv.start()
    # Wait for server to be ready
    for _ in range(20):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1)
            break
        except (urllib.error.URLError, OSError):
            time.sleep(0.05)
    yield state
    srv.stop()


def _post_evaluate(port, tool_name, file_path, tool_input=None):
    """Helper to POST to /evaluate."""
    payload = json.dumps({
        "tool_name": tool_name,
        "file_path": file_path,
        "tool_input": tool_input or {},
    }).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/evaluate",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read())


# ---------------------------------------------------------------------------
# GuardState tests
# ---------------------------------------------------------------------------

class TestGuardState:
    def test_add_event(self, state):
        event = AccessEvent(
            timestamp=time.time(),
            tool_name="Read",
            file_path="src/auth.py",
            tier=4,
            label="READ-WRITE",
            decision="allow",
        )
        state.add_event(event)
        assert len(state.access_log) == 1
        assert state.access_log[0].file_path == "src/auth.py"

    def test_tier_counts(self, state):
        counts = state.tier_counts()
        assert counts[4] == 2  # working_set has 2 patterns
        assert counts[3] == 2  # reference has 2 patterns
        assert counts[2] == 1  # signatures has 1 pattern
        assert counts[1] == 1  # visible has 1 pattern

    def test_promote_file(self, state):
        state.promote_file("new_file.py", 4)
        assert "new_file.py" in state.scope.working_set
        assert state.auto_approved["new_file.py"] == 4

    def test_promote_file_read_only(self, state):
        state.promote_file("readme.txt", 3)
        assert "readme.txt" in state.scope.reference
        assert state.auto_approved["readme.txt"] == 3

    def test_promote_file_signature(self, state):
        state.promote_file("api.pyi", 2)
        assert "api.pyi" in state.scope.signatures
        assert state.auto_approved["api.pyi"] == 2

    def test_pending_approval(self, state):
        req = ApprovalRequest(
            tool_name="Read",
            file_path="blocked.py",
            tier=0,
            label="BLOCKED",
        )
        state.set_pending(req)
        assert state.get_pending() is req
        state.clear_pending()
        assert state.get_pending() is None

    def test_uptime(self, state):
        time.sleep(0.1)
        assert state.uptime() >= 0.1

    def test_access_log_maxlen(self, state):
        for i in range(600):
            state.add_event(AccessEvent(
                timestamp=time.time(),
                tool_name="Read",
                file_path=f"file_{i}.py",
                tier=4,
                label="READ-WRITE",
                decision="allow",
            ))
        assert len(state.access_log) == 500


# ---------------------------------------------------------------------------
# GuardServer tests
# ---------------------------------------------------------------------------

class TestGuardServer:
    def test_health_endpoint(self, server):
        with urllib.request.urlopen(f"http://127.0.0.1:{server.port}/health", timeout=2) as resp:
            data = json.loads(resp.read())
        assert data["status"] == "ok"
        assert "uptime" in data

    def test_evaluate_allow_working_set(self, server):
        result = _post_evaluate(server.port, "Read", "src/auth.py")
        assert result["decision"] == "allow"
        assert result["tier"] == 4

    def test_evaluate_allow_reference_read(self, server):
        result = _post_evaluate(server.port, "Read", "src/core.py")
        assert result["decision"] == "allow"
        assert result["tier"] == 3

    def test_evaluate_deny_reference_write(self, server):
        result = _post_evaluate(server.port, "Edit", "src/core.py")
        assert result["decision"] == "deny"

    def test_evaluate_deny_blocked(self, server):
        result = _post_evaluate(server.port, "Read", "src/db.py")
        assert result["decision"] == "deny"

    def test_evaluate_no_file_path(self, server):
        result = _post_evaluate(server.port, "Read", "")
        assert result["decision"] == "allow"

    def test_access_log_populated(self, server):
        _post_evaluate(server.port, "Read", "src/auth.py")
        _post_evaluate(server.port, "Read", "src/db.py")

        with urllib.request.urlopen(f"http://127.0.0.1:{server.port}/log", timeout=2) as resp:
            data = json.loads(resp.read())

        assert len(data["events"]) == 2
        assert data["events"][0]["decision"] == "allow"
        assert data["events"][1]["decision"] == "deny"

    def test_evaluate_allow_signature_read(self, server):
        result = _post_evaluate(server.port, "Read", "types/api.pyi")
        assert result["decision"] == "allow"
        assert result["tier"] == 2

    def test_evaluate_deny_signature_write(self, server):
        result = _post_evaluate(server.port, "Write", "types/api.pyi")
        assert result["decision"] == "deny"


# ---------------------------------------------------------------------------
# Interactive approval tests
# ---------------------------------------------------------------------------

class TestInteractiveApproval:
    def test_approval_allow(self):
        scope = Scope(
            scope_name="test",
            active=True,
            working_set=["src/auth.py"],
        )
        state = GuardState(scope=scope, interactive=True, port=0)

        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        state.port = port

        srv = GuardServer(state)
        srv.start()

        # Wait for server
        for _ in range(20):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1)
                break
            except (urllib.error.URLError, OSError):
                time.sleep(0.05)

        # Simulate user pressing 'r' after the request arrives
        def approve_after_delay():
            for _ in range(50):
                pending = state.get_pending()
                if pending:
                    pending.response = "r"
                    pending.promoted_tier = 3
                    pending.event.set()
                    return
                time.sleep(0.05)

        t = threading.Thread(target=approve_after_delay, daemon=True)
        t.start()

        result = _post_evaluate(port, "Read", "blocked.py")
        assert result["decision"] == "allow"
        assert "blocked.py" in state.scope.reference

        srv.stop()

    def test_approval_timeout(self):
        """Test that unanswered approval times out and denies."""
        scope = Scope(scope_name="test", active=True, working_set=["src/auth.py"])
        state = GuardState(scope=scope, interactive=True, port=0)

        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        state.port = port

        srv = GuardServer(state)
        srv.start()

        for _ in range(20):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1)
                break
            except (urllib.error.URLError, OSError):
                time.sleep(0.05)

        # Patch timeout to be very short for testing
        from consurg.guard import server as guard_server_mod
        original = guard_server_mod.APPROVAL_TIMEOUT
        guard_server_mod.APPROVAL_TIMEOUT = 0.5

        try:
            result = _post_evaluate(port, "Read", "blocked.py")
            assert result["decision"] == "deny"
        finally:
            guard_server_mod.APPROVAL_TIMEOUT = original
            srv.stop()


# ---------------------------------------------------------------------------
# Lockfile tests
# ---------------------------------------------------------------------------

class TestGuardLockfile:
    def test_write_and_read(self, tmp_path):
        lf = GuardLockfile(tmp_path)
        lf.write(port=9876, scope_name="test")

        data = lf.read()
        assert data["port"] == 9876
        assert data["scope"] == "test"
        assert data["pid"] == os.getpid()

    def test_is_alive_current_pid(self, tmp_path):
        lf = GuardLockfile(tmp_path)
        lf.write(port=9876, scope_name="test")
        assert lf.is_alive() is True

    def test_is_alive_dead_pid(self, tmp_path):
        lf = GuardLockfile(tmp_path)
        lf.path.write_text(json.dumps({"pid": 999999999, "port": 9876, "scope": "test"}))
        assert lf.is_alive() is False

    def test_remove(self, tmp_path):
        lf = GuardLockfile(tmp_path)
        lf.write(port=9876, scope_name="test")
        assert lf.path.exists()
        lf.remove()
        assert not lf.path.exists()

    def test_get_port(self, tmp_path):
        lf = GuardLockfile(tmp_path)
        lf.write(port=9876, scope_name="test")
        assert lf.get_port() == 9876

    def test_get_port_no_lockfile(self, tmp_path):
        lf = GuardLockfile(tmp_path)
        assert lf.get_port() is None

    def test_read_missing(self, tmp_path):
        lf = GuardLockfile(tmp_path)
        assert lf.read() is None

    def test_read_invalid_json(self, tmp_path):
        lf = GuardLockfile(tmp_path)
        lf.path.write_text("not json")
        assert lf.read() is None


# ---------------------------------------------------------------------------
# Fallback behavior test
# ---------------------------------------------------------------------------

class TestFallbackBehavior:
    def test_server_unreachable_returns_none(self):
        """When guard server is not running, _try_guard returns None."""
        from hooks.enforce_guard import _try_guard
        result = _try_guard(99999, "Read", {}, "src/db.py")
        assert result is None
