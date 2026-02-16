"""Tests for consurg.sandbox.seatbelt — macOS Seatbelt profile generation."""

from pathlib import Path

from consurg.sandbox.seatbelt import generate_seatbelt_profile
from consurg.scope import NetworkPolicy, SandboxConfig, Scope


def _scope(**kwargs) -> Scope:
    defaults = {"version": 2, "scope_name": "test", "sandbox": SandboxConfig()}
    defaults.update(kwargs)
    return Scope(**defaults)


class TestSeatbeltProfile:
    def test_starts_with_version_and_deny(self, tmp_path):
        scope = _scope()
        profile = generate_seatbelt_profile(scope, tmp_path)
        assert "(version 1)" in profile
        assert "(deny default)" in profile

    def test_working_set_gets_file_write(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("x = 1")
        scope = _scope(working_set=["src/main.py"])
        profile = generate_seatbelt_profile(scope, tmp_path)
        assert "file-write*" in profile
        assert "file-read-data" in profile

    def test_reference_gets_read_only(self, tmp_path):
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "ref.md").write_text("doc")
        scope = _scope(reference=["docs/ref.md"])
        profile = generate_seatbelt_profile(scope, tmp_path)
        assert "file-read-data" in profile
        # Ensure no write for reference
        lines = profile.splitlines()
        ref_section = False
        for line in lines:
            if "T3" in line:
                ref_section = True
            elif ref_section and "file-write" in line:
                assert False, "reference paths should not have file-write"
            elif ref_section and line.strip() == "":
                break

    def test_unrestricted_network(self, tmp_path):
        scope = _scope(
            sandbox=SandboxConfig(network=NetworkPolicy(policy="unrestricted"))
        )
        profile = generate_seatbelt_profile(scope, tmp_path)
        assert "(allow network*)" in profile

    def test_allowlist_network(self, tmp_path):
        scope = _scope(
            sandbox=SandboxConfig(
                network=NetworkPolicy(
                    policy="allowlist",
                    allow=["api.github.com"],
                )
            )
        )
        profile = generate_seatbelt_profile(scope, tmp_path)
        assert "network-outbound" in profile
        assert "api.github.com" in profile

    def test_denylist_network(self, tmp_path):
        scope = _scope(
            sandbox=SandboxConfig(
                network=NetworkPolicy(
                    policy="denylist",
                    deny=["evil.com"],
                )
            )
        )
        profile = generate_seatbelt_profile(scope, tmp_path)
        assert "(deny network-outbound" in profile
        assert "evil.com" in profile

    def test_tmp_access_included(self, tmp_path):
        scope = _scope()
        profile = generate_seatbelt_profile(scope, tmp_path)
        assert "/tmp" in profile

    def test_process_exec_allowed(self, tmp_path):
        scope = _scope()
        profile = generate_seatbelt_profile(scope, tmp_path)
        assert "(allow process-exec)" in profile
