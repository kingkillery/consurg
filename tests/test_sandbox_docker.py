"""Tests for consurg.sandbox.docker — Docker profile generation from scope tiers."""

from pathlib import Path

from consurg.sandbox.docker import DockerProfile, VolumeMount, generate_docker_profile
from consurg.scope import NetworkPolicy, SandboxConfig, Scope


def _scope(**kwargs) -> Scope:
    defaults = {"version": 2, "scope_name": "test", "sandbox": SandboxConfig()}
    defaults.update(kwargs)
    return Scope(**defaults)


class TestDockerProfile:
    def test_to_run_args_basic(self):
        p = DockerProfile(image="python:3.12-slim", network_mode="none")
        args = p.to_run_args()
        assert "docker" in args
        assert "run" in args
        assert "--network" in args
        assert "none" in args

    def test_to_run_args_volumes(self):
        p = DockerProfile(
            volumes=[VolumeMount("/host/src", "/workspace/src", "rw")],
        )
        args = p.to_run_args()
        assert "-v" in args
        idx = args.index("-v")
        assert args[idx + 1] == "/host/src:/workspace/src:rw"

    def test_to_run_args_env(self):
        p = DockerProfile(env={"FOO": "bar"})
        args = p.to_run_args()
        assert "-e" in args
        idx = args.index("-e")
        assert args[idx + 1] == "FOO=bar"


class TestGenerateDockerProfile:
    def test_working_set_gets_rw_mounts(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("x = 1")
        scope = _scope(working_set=["src/*.py"])
        profile = generate_docker_profile(scope, tmp_path)
        rw_mounts = [v for v in profile.volumes if v.mode == "rw"]
        assert len(rw_mounts) >= 1
        assert any("src" in v.container_path for v in rw_mounts)

    def test_reference_gets_ro_mounts(self, tmp_path):
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "readme.md").write_text("hello")
        scope = _scope(reference=["docs/*.md"])
        profile = generate_docker_profile(scope, tmp_path)
        ro_mounts = [v for v in profile.volumes if v.mode == "ro"]
        assert len(ro_mounts) >= 1

    def test_t0_files_not_mounted(self, tmp_path):
        (tmp_path / "secret").mkdir()
        (tmp_path / "secret" / "key.pem").write_text("secret")
        scope = _scope(working_set=["src/*.py"])
        profile = generate_docker_profile(scope, tmp_path)
        assert not any("secret" in v.host_path for v in profile.volumes)

    def test_network_unrestricted_is_bridge(self, tmp_path):
        scope = _scope(
            sandbox=SandboxConfig(network=NetworkPolicy(policy="unrestricted"))
        )
        profile = generate_docker_profile(scope, tmp_path)
        assert profile.network_mode == "bridge"

    def test_network_empty_allowlist_is_none(self, tmp_path):
        scope = _scope(
            sandbox=SandboxConfig(
                network=NetworkPolicy(policy="allowlist", allow=[])
            )
        )
        profile = generate_docker_profile(scope, tmp_path)
        assert profile.network_mode == "none"

    def test_env_vars_set(self, tmp_path):
        scope = _scope(scope_name="myscope", sandbox=SandboxConfig(autonomy=1))
        profile = generate_docker_profile(scope, tmp_path)
        assert profile.env["CONSURG_SCOPE"] == "myscope"
        assert profile.env["CONSURG_AUTONOMY"] == "1"

    def test_custom_image(self, tmp_path):
        scope = _scope()
        profile = generate_docker_profile(scope, tmp_path, image="node:20-alpine")
        assert profile.image == "node:20-alpine"
