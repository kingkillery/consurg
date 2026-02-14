import pytest
from rich.console import Console
from rich.layout import Layout
from consurg.guard.tui import _build_layout, _build_footer
from consurg.guard.state import GuardState, ApprovalRequest
from consurg.scope import Scope

@pytest.fixture
def scope():
    return Scope(
        scope_name="test-scope",
        active=True,
        working_set=[],
    )

@pytest.fixture
def state(scope):
    return GuardState(scope=scope, interactive=True, port=1234)

def test_footer_content(state):
    """Test that the footer contains the expected text."""
    footer = _build_footer(state)
    console = Console()
    with console.capture() as capture:
        console.print(footer)
    output = capture.get()
    assert "Press Q to quit" in output

def test_layout_structure(state):
    """Test that the layout includes the footer."""
    layout = _build_layout(state)
    # Verify we have header, log, and footer
    # Rich Layouts are accessed by name if set, but accessing by index/children is also possible.
    # The structure is:
    # layout (column)
    #   - header
    #   - log
    #   - footer

    assert layout["header"]
    assert layout["log"]
    assert layout["footer"]

    # Verify footer is visible
    assert layout["footer"].visible

def test_layout_with_approval(state):
    """Test that the layout includes approval and footer when pending."""
    req = ApprovalRequest(
        tool_name="Read",
        file_path="blocked.py",
        tier=0,
        label="BLOCKED",
    )
    state.set_pending(req)

    layout = _build_layout(state)
    assert layout["header"]
    assert layout["log"]
    assert layout["approval"]
    assert layout["footer"]
