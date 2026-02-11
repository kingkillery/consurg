"""Wirer for PuzlD AI (droid) — patches ~/.puzldai/trusted-dirs.json with scope patterns."""

from __future__ import annotations

import json
from pathlib import Path

from consurg.wire.base import BaseWirer, WireResult


class DroidWirer(BaseWirer):
    @property
    def name(self) -> str:
        return "droid (PuzlD AI)"

    def _config_path(self) -> Path:
        return Path.home() / ".puzldai" / "trusted-dirs.json"

    def _consurg_marker(self) -> str:
        return f"consurg:{self.project_dir}"

    def wire(self) -> WireResult:
        config_path = self._config_path()
        config_path.parent.mkdir(parents=True, exist_ok=True)

        if config_path.exists():
            try:
                config = json.loads(config_path.read_text())
            except json.JSONDecodeError:
                config = {}
        else:
            config = {}

        trusted = config.get("trusted_dirs", [])
        marker = self._consurg_marker()

        # Add project dir with consurg marker
        entry = {
            "path": str(self.project_dir),
            "scope": "consurg",
            "marker": marker,
        }

        for existing in trusted:
            if existing.get("marker") == marker:
                return WireResult(
                    success=True,
                    message="Already wired to droid",
                    config_path=config_path,
                )

        trusted.append(entry)
        config["trusted_dirs"] = trusted

        config_path.write_text(json.dumps(config, indent=2))
        return WireResult(
            success=True,
            message="Wired to droid (trusted-dirs.json)",
            config_path=config_path,
        )

    def unwire(self) -> WireResult:
        config_path = self._config_path()
        if not config_path.exists():
            return WireResult(success=True, message="No trusted-dirs.json found")

        try:
            config = json.loads(config_path.read_text())
        except json.JSONDecodeError:
            return WireResult(success=False, message="Invalid trusted-dirs.json")

        trusted = config.get("trusted_dirs", [])
        marker = self._consurg_marker()
        filtered = [d for d in trusted if d.get("marker") != marker]

        if len(filtered) == len(trusted):
            return WireResult(success=True, message="No consurg entry found to remove")

        config["trusted_dirs"] = filtered
        config_path.write_text(json.dumps(config, indent=2))
        return WireResult(
            success=True,
            message="Unwired from droid",
            config_path=config_path,
        )

    def status(self) -> str:
        config_path = self._config_path()
        if not config_path.exists():
            return "not wired"
        try:
            config = json.loads(config_path.read_text())
            trusted = config.get("trusted_dirs", [])
            marker = self._consurg_marker()
            for d in trusted:
                if d.get("marker") == marker:
                    return "wired"
        except (json.JSONDecodeError, KeyError):
            pass
        return "not wired"
