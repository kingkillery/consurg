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
