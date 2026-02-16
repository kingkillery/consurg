import json
import urllib.request
import urllib.error
import pytest
import socket
import time
from consurg.guard.server import GuardServer
from consurg.guard.state import GuardState
from consurg.scope import Scope

@pytest.fixture
def state():
    scope = Scope(
        scope_name="test-scope",
        active=True,
        working_set=["src/auth.py"],
        reference=[],
        signatures=[],
        visible=[],
    )
    return GuardState(scope=scope, interactive=False, port=0)

@pytest.fixture
def server(state):
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
        except:
            time.sleep(0.05)
    yield state
    srv.stop()

def post_evaluate(port, payload):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/evaluate",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.getcode(), json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())

def test_invalid_json(server):
    req = urllib.request.Request(
        f"http://127.0.0.1:{server.port}/evaluate",
        data=b"invalid json",
        headers={"Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(req, timeout=5)
    except urllib.error.HTTPError as e:
        assert e.code == 400
        assert json.loads(e.read()) == {"error": "invalid JSON"}

def test_non_object_json(server):
    code, body = post_evaluate(server.port, ["not", "an", "object"])
    # Current behavior might crash or return 500 if not handled, 
    # but based on the code it will fail at data.get(...)
    # if data is a list, .get() doesn't exist.
    assert code == 400
    assert "error" in body

def test_unhashable_tool_name(server):
    code, body = post_evaluate(server.port, {"tool_name": ["unhashable"]})
    assert code == 400
    assert "error" in body

def test_invalid_file_path_type(server):
    code, body = post_evaluate(server.port, {"tool_name": "Read", "file_path": 123})
    assert code == 400
    assert "error" in body

def test_invalid_tool_input_type(server):
    code, body = post_evaluate(server.port, {"tool_name": "Read", "tool_input": "not a dict"})
    assert code == 400
    assert "error" in body

def test_invalid_nested_file_path(server):
    # Bypass attempt: omit top-level file_path and provide invalid type in tool_input
    code, body = post_evaluate(server.port, {
        "tool_name": "Read",
        "tool_input": {"file_path": 123}
    })
    assert code == 400
    assert "error" in body
    assert "must be a string" in body["error"]


# --- T17: Command injection / bypass attempts ---

from consurg.sandbox.commands import classify_command
from consurg.scope import SandboxConfig


def _sandbox_scope(autonomy=0, command_deny=None):
    return Scope(
        version=2,
        scope_name="sec-test",
        active=True,
        working_set=["src/*.py"],
        sandbox=SandboxConfig(
            autonomy=autonomy,
            command_deny=command_deny or [],
        ),
    )


class TestCommandInjectionPrevention:
    """Verify that shell injection patterns are blocked at low autonomy."""

    def test_pipe_chain_blocked(self):
        r = classify_command("ls | rm -rf /", tier=3, scope=_sandbox_scope(autonomy=0))
        assert not r.allow

    def test_semicolon_chain_blocked(self):
        r = classify_command("echo hello; rm -rf /", tier=3, scope=_sandbox_scope(autonomy=0))
        assert not r.allow

    def test_and_chain_blocked(self):
        r = classify_command("true && rm -rf /", tier=3, scope=_sandbox_scope(autonomy=0))
        assert not r.allow

    def test_or_chain_blocked(self):
        r = classify_command("false || rm -rf /", tier=3, scope=_sandbox_scope(autonomy=0))
        assert not r.allow

    def test_subshell_blocked(self):
        r = classify_command("echo $(cat /etc/passwd)", tier=3, scope=_sandbox_scope(autonomy=0))
        assert not r.allow

    def test_backtick_blocked(self):
        r = classify_command("echo `whoami`", tier=3, scope=_sandbox_scope(autonomy=0))
        assert not r.allow

    def test_env_expansion_blocked(self):
        r = classify_command("echo ${HOME}", tier=3, scope=_sandbox_scope(autonomy=1))
        assert not r.allow

    def test_deny_list_cannot_be_bypassed_by_tier(self):
        """Even at T4, deny list is absolute."""
        scope = _sandbox_scope(autonomy=3, command_deny=["rm -rf *"])
        r = classify_command("rm -rf *", tier=4, scope=scope)
        assert not r.allow

    def test_deny_list_prefix_match(self):
        """Deny entries match prefixes to prevent flag-appending bypass."""
        scope = _sandbox_scope(command_deny=["git push --force"])
        r = classify_command("git push --force --set-upstream origin evil", tier=4, scope=scope)
        assert not r.allow

    def test_safe_command_still_works(self):
        """Sanity: normal commands aren't blocked."""
        r = classify_command("git diff HEAD", tier=3, scope=_sandbox_scope(autonomy=2))
        assert r.allow
