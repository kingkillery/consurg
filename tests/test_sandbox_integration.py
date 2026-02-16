"""Integration tests for the full sandbox pipeline (T16).

Tests the end-to-end flow: v2 scope load → guard start → POST /evaluate → decision.
"""

import json
from http.client import HTTPConnection
from pathlib import Path

import pytest
import yaml

from consurg.guard.server import GuardServer
from consurg.guard.state import GuardState
from consurg.scope import NetworkPolicy, SandboxConfig, Scope, load_scope


def _make_scope(**kwargs) -> Scope:
    defaults = {
        "version": 2,
        "scope_name": "integration-test",
        "active": True,
        "working_set": ["src/*.py"],
        "reference": ["docs/*.md"],
        "sandbox": SandboxConfig(
            backend="none",
            autonomy=2,
            network=NetworkPolicy(policy="allowlist", allow=["api.github.com"]),
            command_deny=["rm -rf *", "git push --force"],
        ),
    }
    defaults.update(kwargs)
    return Scope(**defaults)


def _post(port: int, body: dict) -> dict:
    conn = HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("POST", "/evaluate", json.dumps(body), {"Content-Type": "application/json"})
    return json.loads(conn.getresponse().read())


@pytest.fixture
def free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class TestFullPipeline:
    """End-to-end: scope → guard → evaluate → decision."""

    def test_file_allowed_in_working_set(self, free_port):
        scope = _make_scope()
        state = GuardState(scope, interactive=False, port=free_port)
        server = GuardServer(state)
        server.start()
        try:
            result = _post(free_port, {"tool_name": "Read", "file_path": "src/main.py"})
            assert result["decision"] == "allow"
        finally:
            server.stop()

    def test_file_denied_outside_scope(self, free_port):
        scope = _make_scope()
        state = GuardState(scope, interactive=False, port=free_port)
        server = GuardServer(state)
        server.start()
        try:
            result = _post(free_port, {"tool_name": "Read", "file_path": "secret/key.pem"})
            assert result["decision"] == "deny"
        finally:
            server.stop()

    def test_command_allowed(self, free_port):
        scope = _make_scope()
        state = GuardState(scope, interactive=False, port=free_port)
        server = GuardServer(state)
        server.start()
        try:
            result = _post(free_port, {
                "request_type": "command",
                "command": "echo hello",
            })
            assert result["decision"] == "allow"
        finally:
            server.stop()

    def test_command_denied_by_deny_list(self, free_port):
        scope = _make_scope()
        state = GuardState(scope, interactive=False, port=free_port)
        server = GuardServer(state)
        server.start()
        try:
            result = _post(free_port, {
                "request_type": "command",
                "command": "rm -rf *",
            })
            assert result["decision"] == "deny"
            assert "deny list" in result.get("reason", "")
        finally:
            server.stop()

    def test_network_allowed_on_allowlist(self, free_port):
        scope = _make_scope()
        state = GuardState(scope, interactive=False, port=free_port)
        server = GuardServer(state)
        server.start()
        try:
            result = _post(free_port, {
                "request_type": "network",
                "hostname": "api.github.com",
            })
            assert result["decision"] == "allow"
        finally:
            server.stop()

    def test_network_denied_not_on_allowlist(self, free_port):
        scope = _make_scope()
        state = GuardState(scope, interactive=False, port=free_port)
        server = GuardServer(state)
        server.start()
        try:
            result = _post(free_port, {
                "request_type": "network",
                "hostname": "evil.com",
            })
            assert result["decision"] == "deny"
        finally:
            server.stop()


class TestBackwardCompatV1:
    """v1 scopes should work without sandbox features."""

    def test_v1_scope_file_evaluation_works(self, free_port):
        scope = Scope(
            version=1,
            scope_name="legacy",
            active=True,
            working_set=["src/*.py"],
        )
        state = GuardState(scope, interactive=False, port=free_port)
        server = GuardServer(state)
        server.start()
        try:
            result = _post(free_port, {"tool_name": "Read", "file_path": "src/main.py"})
            assert result["decision"] == "allow"
        finally:
            server.stop()

    def test_v1_scope_command_with_default_sandbox(self, free_port):
        """v1 scope has default SandboxConfig (no deny list, autonomy=2)."""
        scope = Scope(
            version=1,
            scope_name="legacy",
            active=True,
            working_set=["src/*.py"],
        )
        state = GuardState(scope, interactive=False, port=free_port)
        server = GuardServer(state)
        server.start()
        try:
            result = _post(free_port, {
                "request_type": "command",
                "command": "echo hello",
            })
            assert result["decision"] == "allow"
        finally:
            server.stop()


class TestLoadAndEvaluate:
    """Load scope from YAML, then evaluate through the guard."""

    def test_v2_yaml_roundtrip(self, tmp_path, free_port):
        yaml_data = {
            "version": 2,
            "scope": "roundtrip",
            "active": True,
            "working_set": ["src/*.py"],
            "sandbox": {
                "backend": "none",
                "autonomy": 1,
                "network": {"policy": "allowlist", "allow": ["pypi.org"]},
                "commands": {"deny": ["curl * | sh"]},
            },
        }
        scope_file = tmp_path / ".consurg.yaml"
        scope_file.write_text(yaml.dump(yaml_data))

        scope = load_scope(scope_file)
        assert scope is not None
        assert scope.sandbox.autonomy == 1
        assert scope.sandbox.command_deny == ["curl * | sh"]

        state = GuardState(scope, interactive=False, port=free_port)
        server = GuardServer(state)
        server.start()
        try:
            # Command from deny list
            r = _post(free_port, {"request_type": "command", "command": "curl * | sh"})
            assert r["decision"] == "deny"

            # Allowed network host
            r = _post(free_port, {"request_type": "network", "hostname": "pypi.org"})
            assert r["decision"] == "allow"

            # Disallowed network host
            r = _post(free_port, {"request_type": "network", "hostname": "evil.com"})
            assert r["decision"] == "deny"
        finally:
            server.stop()


class TestTierCommandMatrix:
    """Verify the tier-to-command capability matrix end-to-end."""

    def test_t0_scope_denies_all_commands(self, free_port):
        """Scope with empty working_set → tier=0 for commands → deny."""
        scope = Scope(
            version=2,
            scope_name="empty",
            active=True,
            sandbox=SandboxConfig(),
        )
        state = GuardState(scope, interactive=False, port=free_port)
        server = GuardServer(state)
        server.start()
        try:
            r = _post(free_port, {"request_type": "command", "command": "ls"})
            assert r["decision"] == "deny"
        finally:
            server.stop()

    def test_t4_scope_allows_all_commands(self, free_port):
        """Scope with working_set → tier=4 for commands → allow."""
        scope = _make_scope()
        state = GuardState(scope, interactive=False, port=free_port)
        server = GuardServer(state)
        server.start()
        try:
            r = _post(free_port, {"request_type": "command", "command": "python setup.py"})
            assert r["decision"] == "allow"
        finally:
            server.stop()
