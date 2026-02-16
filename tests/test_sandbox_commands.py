"""Tests for consurg.sandbox.commands — command classification against tiers."""

from consurg.sandbox.commands import classify_command, CommandDecision
from consurg.scope import NetworkPolicy, SandboxConfig, Scope


def _scope(
    autonomy: int = 2,
    command_deny: list[str] | None = None,
) -> Scope:
    return Scope(
        version=2,
        sandbox=SandboxConfig(
            autonomy=autonomy,
            command_deny=command_deny or [],
        ),
    )


class TestTierMatrix:
    def test_t0_denies_everything(self):
        r = classify_command("ls", tier=0, scope=_scope())
        assert not r.allow
        assert "no command execution" in r.reason

    def test_t1_allows_ls(self):
        r = classify_command("ls", tier=1, scope=_scope())
        assert r.allow

    def test_t1_allows_stat(self):
        r = classify_command("stat foo.py", tier=1, scope=_scope())
        assert r.allow

    def test_t1_denies_cat(self):
        r = classify_command("cat secret.txt", tier=1, scope=_scope())
        assert not r.allow

    def test_t2_allows_mypy(self):
        r = classify_command("mypy src/", tier=2, scope=_scope())
        assert r.allow

    def test_t2_denies_rm(self):
        r = classify_command("rm -rf /", tier=2, scope=_scope())
        assert not r.allow

    def test_t3_allows_git_diff(self):
        r = classify_command("git diff HEAD", tier=3, scope=_scope())
        assert r.allow

    def test_t3_allows_grep(self):
        r = classify_command("grep -r pattern .", tier=3, scope=_scope())
        assert r.allow

    def test_t3_allows_pytest(self):
        r = classify_command("pytest tests/ -x", tier=3, scope=_scope())
        assert r.allow

    def test_t3_denies_git_push(self):
        r = classify_command("git push origin main", tier=3, scope=_scope())
        assert not r.allow

    def test_t4_allows_everything(self):
        r = classify_command("rm -rf /tmp/test", tier=4, scope=_scope())
        assert r.allow
        assert "full execution" in r.reason

    def test_t4_allows_git_push(self):
        r = classify_command("git push origin main", tier=4, scope=_scope())
        assert r.allow


class TestDenyList:
    def test_deny_list_blocks_exact_match(self):
        scope = _scope(command_deny=["rm -rf *"])
        r = classify_command("rm -rf *", tier=4, scope=scope)
        assert not r.allow
        assert "deny list" in r.reason

    def test_deny_list_blocks_prefix_match(self):
        scope = _scope(command_deny=["git push --force"])
        r = classify_command("git push --force origin main", tier=4, scope=scope)
        assert not r.allow

    def test_deny_list_overrides_tier(self):
        """Deny list is checked before tier capabilities."""
        scope = _scope(command_deny=["ls"])
        r = classify_command("ls", tier=4, scope=scope)
        assert not r.allow

    def test_non_matching_deny_list_allows(self):
        scope = _scope(command_deny=["rm -rf *"])
        r = classify_command("ls -la", tier=4, scope=scope)
        assert r.allow


class TestShellMetacharacters:
    def test_pipe_denied_at_autonomy_0(self):
        scope = _scope(autonomy=0)
        r = classify_command("ls | grep foo", tier=3, scope=scope)
        assert not r.allow
        assert "metacharacters" in r.reason

    def test_pipe_denied_at_autonomy_1(self):
        scope = _scope(autonomy=1)
        r = classify_command("cat file.txt | wc -l", tier=3, scope=scope)
        assert not r.allow

    def test_pipe_allowed_at_autonomy_2(self):
        """At autonomy >= 2, metacharacters are not auto-denied."""
        scope = _scope(autonomy=2)
        r = classify_command("cat file.txt | wc -l", tier=4, scope=scope)
        assert r.allow

    def test_semicolon_denied_at_low_autonomy(self):
        scope = _scope(autonomy=0)
        r = classify_command("echo hello; rm -rf /", tier=3, scope=scope)
        assert not r.allow

    def test_subshell_denied_at_low_autonomy(self):
        scope = _scope(autonomy=1)
        r = classify_command("echo $(cat /etc/passwd)", tier=3, scope=scope)
        assert not r.allow

    def test_backtick_denied_at_low_autonomy(self):
        scope = _scope(autonomy=0)
        r = classify_command("echo `whoami`", tier=3, scope=scope)
        assert not r.allow


class TestEdgeCases:
    def test_empty_command_denied(self):
        r = classify_command("", tier=4, scope=_scope())
        assert not r.allow

    def test_whitespace_only_denied(self):
        r = classify_command("   ", tier=4, scope=_scope())
        assert not r.allow

    def test_decision_has_tier(self):
        r = classify_command("ls", tier=3, scope=_scope())
        assert r.tier == 3
