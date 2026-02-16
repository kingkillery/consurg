import pytest
from unittest.mock import MagicMock, patch
from typer.testing import CliRunner
from consurg.cli import app

runner = CliRunner()

@pytest.fixture
def in_tmp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path

def test_trace_shows_spinner(in_tmp):
    (in_tmp / "main.py").write_text("import foo")
    (in_tmp / "foo.py").write_text("")

    with patch("consurg.cli.console.status") as mock_status:
        # Mock the context manager behavior
        mock_status.return_value.__enter__.return_value = None

        result = runner.invoke(app, ["trace", "main.py"])

        assert result.exit_code == 0, result.output
        mock_status.assert_called_with("[bold green]Tracing dependencies...[/bold green]")

def test_git_diff_shows_spinner(in_tmp):
    (in_tmp / "main.py").write_text("")

    with patch("consurg.cli.console.status") as mock_status, \
         patch("subprocess.run") as mock_run:

        # Mock status context
        mock_status.return_value.__enter__.return_value = None

        # Mock subprocess calls
        # 1. detect base branch (git rev-parse) -> main
        # 2. git diff -> main.py

        mock_branch = MagicMock()
        mock_branch.returncode = 0
        mock_branch.stdout = "main"

        mock_diff = MagicMock()
        mock_diff.returncode = 0
        mock_diff.stdout = "main.py"

        # side_effect iterates through calls
        mock_run.side_effect = [mock_branch, mock_diff]

        result = runner.invoke(app, ["git-diff"])

        assert result.exit_code == 0, result.output
        mock_status.assert_called_with("[bold green]Analyzing diff...[/bold green]")

def test_init_shows_hint(in_tmp):
    result = runner.invoke(app, ["init", "my-scope"])
    assert result.exit_code == 0, result.output
    assert "Next: Run 'consurg add <files>'" in result.output
