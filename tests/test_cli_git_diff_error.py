import sys
import importlib
from unittest.mock import MagicMock, patch
import subprocess
import pytest

# Define a real exception for typer.Exit
class MockTyperExit(BaseException):
    def __init__(self, code=0):
        self.code = code
        super().__init__(f"Exit with code {code}")

# Mock dependencies
mock_typer = MagicMock()
mock_typer.Exit = MockTyperExit

def mock_decorator(f):
    return f

mock_app = MagicMock()
mock_app.command.return_value = mock_decorator
mock_typer.Typer.return_value = mock_app
sys.modules["typer"] = mock_typer

mock_yaml = MagicMock()
sys.modules["yaml"] = mock_yaml

# Mock rich and its components
mock_rich = MagicMock()
mock_rich_console = MagicMock()

class MockConsole:
    def __init__(self, *args, **kwargs): pass
    def print(self, *args, **kwargs):
        pass
    def status(self, *args, **kwargs):
        return MagicMock(__enter__=lambda s: None, __exit__=lambda s, *a: None)

mock_rich_console.Console = MockConsole
sys.modules["rich"] = mock_rich
sys.modules["rich.console"] = mock_rich_console
sys.modules["rich.panel"] = MagicMock()
sys.modules["rich.table"] = MagicMock()

# Mock other internal dependencies
sys.modules["consurg.adapters"] = MagicMock()
sys.modules["consurg.audit"] = MagicMock()
sys.modules["consurg.pk_agents"] = MagicMock()
sys.modules["consurg.scope"] = MagicMock()
sys.modules["consurg.trace"] = MagicMock()
sys.modules["consurg.enforce"] = MagicMock()
sys.modules["consurg.file_context_ui"] = MagicMock()

# Import the module
if 'consurg.cli' in sys.modules:
    del sys.modules['consurg.cli']
import consurg.cli

def test_git_diff_git_not_installed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    importlib.reload(consurg.cli)

    with patch("consurg.cli.subprocess.run", side_effect=FileNotFoundError):
        # Patch typer.Exit so it actually uses the passed code
        with patch("consurg.cli.typer.Exit", side_effect=lambda code: MockTyperExit(code)):
            with pytest.raises(MockTyperExit) as excinfo:
                consurg.cli.git_diff_cmd(base="main", apply=False)
            assert excinfo.value.code == 1

def test_git_diff_called_process_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    importlib.reload(consurg.cli)

    e = subprocess.CalledProcessError(1, "git")
    e.stderr = "git diff failed"
    with patch("consurg.cli.subprocess.run", side_effect=e):
        with patch("consurg.cli.typer.Exit", side_effect=lambda code: MockTyperExit(code)):
            with pytest.raises(MockTyperExit) as excinfo:
                 consurg.cli.git_diff_cmd(base="main", apply=False)
            assert excinfo.value.code == 1

def test_git_diff_success(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    importlib.reload(consurg.cli)

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "file1.py\nfile2.py"
    mock_result.stderr = ""

    with patch("consurg.cli.subprocess.run", return_value=mock_result):
        with patch("consurg.cli._build_graph") as mock_build_graph:
            mock_graph = MagicMock()
            mock_build_graph.return_value = mock_graph
            mock_graph.classify_tiers.return_value = {"file1.py": 4, "file2.py": 3}

            consurg.cli.git_diff_cmd(base="main", apply=False)

            mock_build_graph.assert_called_once()
