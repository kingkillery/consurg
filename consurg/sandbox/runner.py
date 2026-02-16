"""SandboxRunner — orchestrate backend detection, profile generation, and sandboxed execution."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from consurg.sandbox.detect import resolve_backend
from consurg.scope import Scope


@dataclass
class SandboxResult:
    returncode: int
    backend: str
    stdout: str = ""
    stderr: str = ""


class SandboxRunner:
    """Orchestrates sandbox execution: detect backend → generate profile → run."""

    def __init__(self, scope: Scope, backend: str, project_root: Path):
        self.scope = scope
        self.backend = resolve_backend(backend)
        self.project_root = project_root

    def run(self, args: list[str], env: dict[str, str] | None = None) -> SandboxResult:
        """Run a command inside the resolved sandbox.

        Args:
            args: Command and arguments to execute.
            env: Environment variables to pass.

        Returns:
            SandboxResult with return code and backend used.
        """
        if self.backend == "none":
            # No sandbox — run directly (existing behavior)
            return self._run_direct(args, env)
        elif self.backend == "docker":
            return self._run_docker(args, env)
        elif self.backend == "seatbelt":
            return self._run_seatbelt(args, env)
        elif self.backend == "wsl2":
            return self._run_wsl2(args, env)
        else:
            return self._run_direct(args, env)

    def _run_direct(self, args: list[str], env: dict[str, str] | None) -> SandboxResult:
        """Run without sandbox (pass-through)."""
        result = subprocess.run(args, env=env, capture_output=True, text=True, errors="replace")
        return SandboxResult(
            returncode=result.returncode,
            backend="none",
            stdout=result.stdout,
            stderr=result.stderr,
        )

    def _run_docker(self, args: list[str], env: dict[str, str] | None) -> SandboxResult:
        """Run inside a Docker container with scope-derived mounts."""
        from consurg.sandbox.docker import generate_docker_profile

        profile = generate_docker_profile(self.scope, self.project_root)
        # Merge environment
        if env:
            profile.env.update(env)

        docker_args = profile.to_run_args()
        docker_args.extend(args)

        result = subprocess.run(docker_args, capture_output=True, text=True, errors="replace")
        return SandboxResult(
            returncode=result.returncode,
            backend="docker",
            stdout=result.stdout,
            stderr=result.stderr,
        )

    def _run_seatbelt(self, args: list[str], env: dict[str, str] | None) -> SandboxResult:
        """Run inside a macOS Seatbelt sandbox."""
        import tempfile

        from consurg.sandbox.seatbelt import generate_seatbelt_profile

        profile_str = generate_seatbelt_profile(self.scope, self.project_root)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".sb", delete=False) as f:
            f.write(profile_str)
            profile_path = f.name

        try:
            sb_args = ["sandbox-exec", "-f", profile_path] + args
            result = subprocess.run(sb_args, env=env, capture_output=True, text=True, errors="replace")
            return SandboxResult(
                returncode=result.returncode,
                backend="seatbelt",
                stdout=result.stdout,
                stderr=result.stderr,
            )
        finally:
            Path(profile_path).unlink(missing_ok=True)

    def _run_wsl2(self, args: list[str], env: dict[str, str] | None) -> SandboxResult:
        """Run inside WSL2 with scope-derived bind mounts."""
        from consurg.sandbox.wsl2 import generate_wsl2_profile

        profile = generate_wsl2_profile(self.scope, self.project_root)

        # Build setup + command + teardown script
        script_lines = profile.setup_commands.copy()
        # Export env vars
        for key, val in profile.env_vars.items():
            script_lines.append(f"export {key}={val!r}")
        if env:
            for key, val in env.items():
                script_lines.append(f"export {key}={val!r}")
        # Change to workspace and run command
        script_lines.append(f"cd {profile.workspace_dir}")
        script_lines.append(" ".join(args))
        # Capture exit code before teardown
        script_lines.append("_EC=$?")
        script_lines.extend(profile.teardown_commands)
        script_lines.append("exit $_EC")

        script = "\n".join(script_lines)
        wsl_args = ["wsl", "-d", profile.wsl_distro, "--", "bash", "-c", script]

        result = subprocess.run(wsl_args, capture_output=True, text=True, errors="replace")
        return SandboxResult(
            returncode=result.returncode,
            backend="wsl2",
            stdout=result.stdout,
            stderr=result.stderr,
        )
