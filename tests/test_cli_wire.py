import pytest
from typer.testing import CliRunner
from unittest.mock import MagicMock, patch
from pathlib import Path

from consurg.cli import app
from consurg.wire.base import WireResult

runner = CliRunner()

def test_wire_success():
    mock_wirer = MagicMock()
    mock_wirer.wire.return_value = WireResult(success=True, message="Wired successfully", config_path=Path("/path/to/config"))
    mock_wirer.status.return_value = "wired"
    
    # We patch consurg.wire.WIRERS because it's imported inside the wire command
    with patch("consurg.wire.WIRERS", {"test-tool": lambda: mock_wirer}):
        result = runner.invoke(app, ["wire", "test-tool"])
        assert result.exit_code == 0
        assert "Wired successfully" in result.output
        # Handle both Windows (backslash) and Unix (forward slash) paths
        assert "/path/to/config" in result.output.replace("\\", "/")
        assert "Status: wired" in result.output
        mock_wirer.wire.assert_called_once()
        mock_wirer.status.assert_called_once()

def test_wire_unwire_success():
    mock_wirer = MagicMock()
    mock_wirer.unwire.return_value = WireResult(success=True, message="Unwired successfully")
    mock_wirer.status.return_value = "not wired"
    
    with patch("consurg.wire.WIRERS", {"test-tool": lambda: mock_wirer}):
        result = runner.invoke(app, ["wire", "test-tool", "--unwire"])
        assert result.exit_code == 0
        assert "Unwired successfully" in result.output
        assert "Status: not wired" in result.output
        mock_wirer.unwire.assert_called_once()
        mock_wirer.status.assert_called_once()

def test_wire_unknown_tool():
    # Even if we don't mock WIRERS, "unknown-tool" should not be in the real WIRERS
    result = runner.invoke(app, ["wire", "unknown-tool"])
    assert result.exit_code == 1
    assert "Unknown tool 'unknown-tool'" in result.output

def test_wire_failure():
    mock_wirer = MagicMock()
    mock_wirer.wire.return_value = WireResult(success=False, message="Wiring failed")
    
    with patch("consurg.wire.WIRERS", {"test-tool": lambda: mock_wirer}):
        result = runner.invoke(app, ["wire", "test-tool"])
        assert result.exit_code == 1
        assert "Wiring failed" in result.output
        mock_wirer.wire.assert_called_once()
        # Should not call status on failure based on current implementation
        mock_wirer.status.assert_not_called()
