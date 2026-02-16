"""Tests for guard server command and network evaluation (T6)."""

import json
import threading
from http.client import HTTPConnection

import pytest

from consurg.guard.server import GuardServer
from consurg.guard.state import GuardState
from consurg.scope import NetworkPolicy, SandboxConfig, Scope


def _make_scope(**kwargs) -> Scope:
    defaults = {
        "version": 2,
        "scope_name": "test",
        "active": True,
        "working_set": ["src/*.py"],
    }
    defaults.update(kwargs)
    return Scope(**defaults)


def _post_evaluate(port: int, body: dict) -> dict:
    conn = HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("POST", "/evaluate", json.dumps(body), {"Content-Type": "application/json"})
    resp = conn.getresponse()
    return json.loads(resp.read())


@pytest.fixture
def guard_port():
    """Start a guard server on a free port and yield the port."""
    import socket
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


class TestCommandEvaluation:
    def test_command_allow_at_t4(self, guard_port):
        scope = _make_scope(sandbox=SandboxConfig(autonomy=2))
        state = GuardState(scope, interactive=False, port=guard_port)
        server = GuardServer(state)
        server.start()
        try:
            result = _post_evaluate(guard_port, {
                "request_type": "command",
                "tool_name": "Bash",
                "command": "ls -la",
            })
            assert result["decision"] == "allow"
        finally:
            server.stop()

    def test_command_deny_from_deny_list(self, guard_port):
        scope = _make_scope(
            sandbox=SandboxConfig(
                autonomy=2,
                command_deny=["rm -rf *"],
            )
        )
        state = GuardState(scope, interactive=False, port=guard_port)
        server = GuardServer(state)
        server.start()
        try:
            result = _post_evaluate(guard_port, {
                "request_type": "command",
                "tool_name": "Bash",
                "command": "rm -rf *",
            })
            assert result["decision"] == "deny"
            assert "deny list" in result.get("reason", "")
        finally:
            server.stop()

    def test_empty_command_allows(self, guard_port):
        scope = _make_scope()
        state = GuardState(scope, interactive=False, port=guard_port)
        server = GuardServer(state)
        server.start()
        try:
            result = _post_evaluate(guard_port, {
                "request_type": "command",
                "tool_name": "Bash",
                "command": "",
            })
            assert result["decision"] == "allow"
            assert "no command" in result.get("message", "")
        finally:
            server.stop()


class TestNetworkEvaluation:
    def test_network_allow_unrestricted(self, guard_port):
        scope = _make_scope(sandbox=SandboxConfig())
        state = GuardState(scope, interactive=False, port=guard_port)
        server = GuardServer(state)
        server.start()
        try:
            result = _post_evaluate(guard_port, {
                "request_type": "network",
                "hostname": "example.com",
            })
            assert result["decision"] == "allow"
        finally:
            server.stop()

    def test_network_deny_from_deny_list(self, guard_port):
        scope = _make_scope(
            sandbox=SandboxConfig(
                network=NetworkPolicy(
                    policy="denylist",
                    deny=["evil.com"],
                ),
            )
        )
        state = GuardState(scope, interactive=False, port=guard_port)
        server = GuardServer(state)
        server.start()
        try:
            result = _post_evaluate(guard_port, {
                "request_type": "network",
                "hostname": "evil.com",
            })
            assert result["decision"] == "deny"
            assert "deny list" in result.get("reason", "")
        finally:
            server.stop()

    def test_empty_hostname_allows(self, guard_port):
        scope = _make_scope()
        state = GuardState(scope, interactive=False, port=guard_port)
        server = GuardServer(state)
        server.start()
        try:
            result = _post_evaluate(guard_port, {
                "request_type": "network",
                "hostname": "",
            })
            assert result["decision"] == "allow"
        finally:
            server.stop()


class TestBackwardCompat:
    def test_file_request_without_request_type(self, guard_port):
        """Omitting request_type defaults to file evaluation."""
        scope = _make_scope()
        state = GuardState(scope, interactive=False, port=guard_port)
        server = GuardServer(state)
        server.start()
        try:
            result = _post_evaluate(guard_port, {
                "tool_name": "Read",
                "file_path": "src/main.py",
            })
            assert result["decision"] == "allow"
        finally:
            server.stop()

    def test_file_request_explicit_type(self, guard_port):
        scope = _make_scope()
        state = GuardState(scope, interactive=False, port=guard_port)
        server = GuardServer(state)
        server.start()
        try:
            result = _post_evaluate(guard_port, {
                "request_type": "file",
                "tool_name": "Read",
                "file_path": "src/main.py",
            })
            assert result["decision"] == "allow"
        finally:
            server.stop()

    def test_invalid_request_type_returns_400(self, guard_port):
        scope = _make_scope()
        state = GuardState(scope, interactive=False, port=guard_port)
        server = GuardServer(state)
        server.start()
        try:
            conn = HTTPConnection("127.0.0.1", guard_port, timeout=5)
            conn.request("POST", "/evaluate",
                         json.dumps({"request_type": "invalid"}),
                         {"Content-Type": "application/json"})
            resp = conn.getresponse()
            assert resp.status == 400
        finally:
            server.stop()


class TestAccessLog:
    def test_command_logged(self, guard_port):
        scope = _make_scope(sandbox=SandboxConfig())
        state = GuardState(scope, interactive=False, port=guard_port)
        server = GuardServer(state)
        server.start()
        try:
            _post_evaluate(guard_port, {
                "request_type": "command",
                "tool_name": "Bash",
                "command": "echo hello",
            })
            assert len(state.access_log) == 1
            event = state.access_log[0]
            assert event.request_type == "command"
            assert event.command == "echo hello"
        finally:
            server.stop()

    def test_network_logged(self, guard_port):
        scope = _make_scope(sandbox=SandboxConfig())
        state = GuardState(scope, interactive=False, port=guard_port)
        server = GuardServer(state)
        server.start()
        try:
            _post_evaluate(guard_port, {
                "request_type": "network",
                "hostname": "example.com",
            })
            assert len(state.access_log) == 1
            event = state.access_log[0]
            assert event.request_type == "network"
            assert event.hostname == "example.com"
        finally:
            server.stop()
