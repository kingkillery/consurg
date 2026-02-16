"""Tests for consurg.sandbox.network — network classification against tiers."""

from consurg.sandbox.network import classify_network, NetworkDecision
from consurg.scope import NetworkPolicy, SandboxConfig, Scope


def _scope(
    network_policy: str = "unrestricted",
    allow: list[str] | None = None,
    deny: list[str] | None = None,
) -> Scope:
    return Scope(
        version=2,
        sandbox=SandboxConfig(
            network=NetworkPolicy(
                policy=network_policy,
                allow=allow or [],
                deny=deny or [],
            ),
        ),
    )


class TestTierCapabilities:
    def test_t0_denies_everything(self):
        r = classify_network("example.com", tier=0, scope=_scope())
        assert not r.allow
        assert "no network egress" in r.reason

    def test_t1_denies_connections(self):
        r = classify_network("example.com", tier=1, scope=_scope())
        assert not r.allow
        assert "DNS resolve only" in r.reason

    def test_t2_allows_localhost(self):
        r = classify_network("localhost", tier=2, scope=_scope())
        assert r.allow

    def test_t2_allows_127(self):
        r = classify_network("127.0.0.1", tier=2, scope=_scope())
        assert r.allow

    def test_t2_denies_external(self):
        r = classify_network("api.github.com", tier=2, scope=_scope())
        assert not r.allow
        assert "only localhost" in r.reason

    def test_t4_allows_everything(self):
        r = classify_network("anything.com", tier=4, scope=_scope())
        assert r.allow
        assert "full network" in r.reason


class TestAllowlistPolicy:
    def test_t3_allowlist_permits_listed_host(self):
        scope = _scope(
            network_policy="allowlist",
            allow=["api.github.com", "pypi.org"],
        )
        r = classify_network("api.github.com", tier=3, scope=scope)
        assert r.allow
        assert "allow list" in r.reason

    def test_t3_allowlist_denies_unlisted_host(self):
        scope = _scope(
            network_policy="allowlist",
            allow=["api.github.com"],
        )
        r = classify_network("evil.com", tier=3, scope=scope)
        assert not r.allow
        assert "not in allow list" in r.reason

    def test_t3_allowlist_wildcard(self):
        scope = _scope(
            network_policy="allowlist",
            allow=["*.github.com"],
        )
        r = classify_network("api.github.com", tier=3, scope=scope)
        assert r.allow

    def test_t3_allowlist_wildcard_no_match(self):
        scope = _scope(
            network_policy="allowlist",
            allow=["*.github.com"],
        )
        r = classify_network("pypi.org", tier=3, scope=scope)
        assert not r.allow


class TestDenylistPolicy:
    def test_t3_denylist_blocks_listed_host(self):
        scope = _scope(
            network_policy="denylist",
            deny=["evil.com"],
        )
        r = classify_network("evil.com", tier=3, scope=scope)
        assert not r.allow
        assert "deny list" in r.reason

    def test_t3_denylist_allows_unlisted_host(self):
        scope = _scope(
            network_policy="denylist",
            deny=["evil.com"],
        )
        r = classify_network("good.com", tier=3, scope=scope)
        assert r.allow

    def test_denylist_wildcard(self):
        scope = _scope(
            network_policy="denylist",
            deny=["*.malware.net"],
        )
        r = classify_network("bad.malware.net", tier=3, scope=scope)
        assert not r.allow

    def test_deny_overrides_tier_4(self):
        """Deny list is checked even at T4."""
        scope = _scope(
            network_policy="denylist",
            deny=["evil.com"],
        )
        r = classify_network("evil.com", tier=4, scope=scope)
        assert not r.allow


class TestUnrestrictedPolicy:
    def test_t3_unrestricted_allows_everything(self):
        scope = _scope(network_policy="unrestricted")
        r = classify_network("anything.com", tier=3, scope=scope)
        assert r.allow
        assert "unrestricted" in r.reason


class TestEdgeCases:
    def test_empty_hostname_denied(self):
        r = classify_network("", tier=4, scope=_scope())
        assert not r.allow

    def test_whitespace_hostname_denied(self):
        r = classify_network("   ", tier=4, scope=_scope())
        assert not r.allow

    def test_decision_has_hostname(self):
        r = classify_network("example.com", tier=3, scope=_scope())
        assert r.hostname == "example.com"

    def test_case_insensitive_matching(self):
        scope = _scope(
            network_policy="allowlist",
            allow=["API.GitHub.com"],
        )
        r = classify_network("api.github.com", tier=3, scope=scope)
        assert r.allow
