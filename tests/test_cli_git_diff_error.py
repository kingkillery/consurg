import importlib
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest


# Define a real exception for typer.Exit
class MockTyperExit(BaseException):
    def __init__(self, code=0):
        self.code = code
        super().__init__(f"Exit with code {code}")


# Names this module replaces in sys.modules. Mock installation happens in
# setup_module (NOT at import time) so pytest's collection of other test
# modules never sees the mocks, and teardown_module restores the originals.
_MOCKED_MODULE_NAMES = [
    "typer",
    "yaml",
    "rich",
    "rich.console",
    "rich.panel",
    "rich.table",
    "consurg.adapters",
    "consurg.audit",
    "consurg.pk_agents",
    "consurg.scope",
    "consurg.trace",
    "consurg.enforce",
    "consurg.file_context_ui",
    "consurg.render",
]
_original_modules: dict = {}
_original_cli = None
cli = None  # the consurg.cli module imported against the mocks


class MockConsole:
    def __init__(self, *args, **kwargs):
        pass

    def print(self, *args, **kwargs):
        pass

    def status(self, *args, **kwargs):
        return MagicMock(__enter__=lambda s: None, __exit__=lambda s, *a: None)


def setup_module():
    global cli, _original_cli
    _original_modules.update(
        {name: sys.modules.get(name) for name in _MOCKED_MODULE_NAMES}
    )
    _original_cli = sys.modules.get("consurg.cli")

    mock_typer = MagicMock()
    mock_typer.Exit = MockTyperExit

    def mock_decorator(f):
        return f

    mock_app = MagicMock()
    mock_app.command.return_value = mock_decorator
    mock_typer.Typer.return_value = mock_app
    sys.modules["typer"] = mock_typer

    sys.modules["yaml"] = MagicMock()

    mock_rich_console = MagicMock()
    mock_rich_console.Console = MockConsole
    sys.modules["rich"] = MagicMock()
    sys.modules["rich.console"] = mock_rich_console
    sys.modules["rich.panel"] = MagicMock()
    sys.modules["rich.table"] = MagicMock()

    sys.modules["consurg.adapters"] = MagicMock()
    sys.modules["consurg.audit"] = MagicMock()
    sys.modules["consurg.pk_agents"] = MagicMock()
    sys.modules["consurg.scope"] = MagicMock()
    sys.modules["consurg.trace"] = MagicMock()
    sys.modules["consurg.enforce"] = MagicMock()
    sys.modules["consurg.file_context_ui"] = MagicMock()
    sys.modules["consurg.render"] = MagicMock()

    sys.modules.pop("consurg.cli", None)
    import consurg.cli as cli_module

    cli = cli_module


def teardown_module():
    for name, original in _original_modules.items():
        if original is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = original
    sys.modules.pop("consurg.cli", None)
    if _original_cli is not None:
        # Reinstall the original module object, then re-execute it against the
        # restored real dependencies (reload requires it in sys.modules).
        sys.modules["consurg.cli"] = _original_cli
        importlib.reload(_original_cli)


def test_git_diff_git_not_installed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    importlib.reload(cli)

    with patch("consurg.cli.subprocess.run", side_effect=FileNotFoundError):
        # Patch typer.Exit so it actually uses the passed code
        with patch("consurg.cli.typer.Exit", side_effect=lambda code: MockTyperExit(code)):
            with pytest.raises(MockTyperExit) as excinfo:
                cli.git_diff_cmd(base="main", apply=False)
            assert excinfo.value.code == 1


def test_git_diff_called_process_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    importlib.reload(cli)

    e = subprocess.CalledProcessError(1, "git")
    e.stderr = "git diff failed"
    with patch("consurg.cli.subprocess.run", side_effect=e):
        with patch("consurg.cli.typer.Exit", side_effect=lambda code: MockTyperExit(code)):
            with pytest.raises(MockTyperExit) as excinfo:
                cli.git_diff_cmd(base="main", apply=False)
            assert excinfo.value.code == 1


def test_git_diff_success(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    importlib.reload(cli)

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "file1.py\nfile2.py"
    mock_result.stderr = ""

    with patch("consurg.cli.subprocess.run", return_value=mock_result):
        with patch("consurg.cli._build_graph") as mock_build_graph:
            mock_graph = MagicMock()
            mock_build_graph.return_value = mock_graph
            mock_graph.classify_tiers.return_value = {"file1.py": 4, "file2.py": 3}

            cli.git_diff_cmd(base="main", apply=False)

            mock_build_graph.assert_called_once()
