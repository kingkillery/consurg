"""Base class for tool wirers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass
class WireResult:
    """Result of a wire/unwire operation."""

    success: bool
    message: str
    config_path: Path | None = None


class BaseWirer(ABC):
    """Abstract base for tool-specific wiring."""

    def __init__(self, project_dir: str | Path | None = None):
        self.project_dir = Path(project_dir) if project_dir else Path.cwd()
        self.hook_script = self._find_hook_script()

    def _find_hook_script(self) -> Path:
        """Locate the enforce_guard.py hook script."""
        # Check relative to project dir first
        candidates = [
            self.project_dir / "hooks" / "enforce_guard.py",
            Path(__file__).resolve().parent.parent.parent / "hooks" / "enforce_guard.py",
        ]
        for p in candidates:
            if p.exists():
                return p.resolve()
        # Default to the expected location
        return (self.project_dir / "hooks" / "enforce_guard.py").resolve()

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable tool name."""

    @abstractmethod
    def wire(self) -> WireResult:
        """Install hooks/config for this tool."""

    @abstractmethod
    def unwire(self) -> WireResult:
        """Remove hooks/config for this tool."""

    @abstractmethod
    def status(self) -> str:
        """Return current wiring status: 'wired', 'not wired', or 'partial'."""
