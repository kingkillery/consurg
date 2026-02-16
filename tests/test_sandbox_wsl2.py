"""Tests for consurg.sandbox.wsl2 — WSL2 profile generation."""

from pathlib import Path

from consurg.sandbox.wsl2 import WSL2Profile, generate_wsl2_profile, windows_to_wsl_path
from consurg.scope import SandboxConfig, Scope


def _scope(**kwargs) -> Scope:
    defaults = {"version": 2, "scope_name": "test", "sandbox": SandboxConfig()}
    defaults.update(kwargs)
    return Scope(**defaults)


class TestWindowsToWslPath:
    def test_c_drive(self):
        assert windows_to_wsl_path("C:\\Users\\foo\\bar") == "/mnt/c/Users/foo/bar"

    def test_d_drive(self):
        assert windows_to_wsl_path("D:\\data") == "/mnt/d/data"

    def test_forward_slashes(self):
        assert windows_to_wsl_path("C:/Users/foo") == "/mnt/c/Users/foo"

    def test_lowercase_drive(self):
        assert windows_to_wsl_path("c:\\temp") == "/mnt/c/temp"

    def test_unix_path_unchanged(self):
        assert windows_to_wsl_path("/home/user/code") == "/home/user/code"

    def test_relative_path_unchanged(self):
        assert windows_to_wsl_path("src/main.py") == "src/main.py"


class TestGenerateWsl2Profile:
    def test_creates_workspace_dir(self, tmp_path):
        scope = _scope()
        profile = generate_wsl2_profile(scope, tmp_path)
        assert any("mkdir" in cmd for cmd in profile.setup_commands)

    def test_working_set_gets_rw_mount(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("x = 1")
        scope = _scope(working_set=["src/*.py"])
        profile = generate_wsl2_profile(scope, tmp_path)
        bind_cmds = [c for c in profile.setup_commands if "mount --bind" in c and "-o ro" not in c]
        assert len(bind_cmds) >= 1

    def test_reference_gets_ro_mount(self, tmp_path):
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "ref.md").write_text("doc")
        scope = _scope(reference=["docs/*.md"])
        profile = generate_wsl2_profile(scope, tmp_path)
        ro_cmds = [c for c in profile.setup_commands if "-o ro" in c]
        assert len(ro_cmds) >= 1

    def test_teardown_unmounts(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("x = 1")
        scope = _scope(working_set=["src/*.py"])
        profile = generate_wsl2_profile(scope, tmp_path)
        assert any("umount" in cmd for cmd in profile.teardown_commands)
        assert any("rm -rf" in cmd for cmd in profile.teardown_commands)

    def test_env_vars_set(self, tmp_path):
        scope = _scope(scope_name="mytest", sandbox=SandboxConfig(autonomy=3))
        profile = generate_wsl2_profile(scope, tmp_path)
        assert profile.env_vars["CONSURG_SCOPE"] == "mytest"
        assert profile.env_vars["CONSURG_AUTONOMY"] == "3"

    def test_custom_distro(self, tmp_path):
        scope = _scope()
        profile = generate_wsl2_profile(scope, tmp_path, wsl_distro="Debian")
        assert profile.wsl_distro == "Debian"

    def test_no_duplicate_mounts(self, tmp_path):
        """If a dir is in both working_set and reference, only mount once (rw wins)."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("x = 1")
        scope = _scope(working_set=["src/*.py"], reference=["src/*.py"])
        profile = generate_wsl2_profile(scope, tmp_path)
        mount_cmds = [c for c in profile.setup_commands if "mount --bind" in c]
        # Should have exactly 1 mount (rw), not 2
        assert len(mount_cmds) == 1
