"""Classify network access against tier capabilities and scope policies."""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch

from consurg.scope import Scope

# Tier-to-network capability levels.
# "none" = no egress, "dns" = resolve only, "localhost" = loopback only,
# "allowlist" = only scope-listed hosts, "full" = unrestricted.
TIER_NETWORK_CAPABILITIES: dict[int, str] = {
    0: "none",
    1: "dns",
    2: "localhost",
    3: "allowlist",
    4: "full",
}

_LOCALHOST_NAMES = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


@dataclass
class NetworkDecision:
    allow: bool
    reason: str
    tier: int
    hostname: str


def _matches_host_pattern(hostname: str, patterns: list[str]) -> str | None:
    """Check if hostname matches any pattern (supports wildcards like *.github.com)."""
    for pattern in patterns:
        if fnmatch(hostname.lower(), pattern.lower()):
            return pattern
    return None


def classify_network(
    hostname: str, tier: int, scope: Scope
) -> NetworkDecision:
    """Classify whether network access to a hostname is allowed at the given tier.

    Decision order:
    1. Scope network deny list (always deny)
    2. Tier capability level
    3. Scope network allow list (for allowlist policy at T3)
    """
    if not hostname or not hostname.strip():
        return NetworkDecision(
            allow=False, reason="empty hostname", tier=tier, hostname=hostname
        )

    hostname = hostname.strip().lower()
    network = scope.sandbox.network

    # 1. Explicit deny list (always checked first)
    deny_match = _matches_host_pattern(hostname, network.deny)
    if deny_match is not None:
        return NetworkDecision(
            allow=False,
            reason=f"hostname matches deny list pattern: {deny_match!r}",
            tier=tier,
            hostname=hostname,
        )

    # 2. Tier capability level
    cap = TIER_NETWORK_CAPABILITIES.get(tier, "none")

    if cap == "none":
        return NetworkDecision(
            allow=False,
            reason=f"tier {tier}: no network egress",
            tier=tier,
            hostname=hostname,
        )

    if cap == "dns":
        # DNS-only: we can't actually distinguish DNS from connection here,
        # so deny all actual connections at T1.
        return NetworkDecision(
            allow=False,
            reason=f"tier {tier}: DNS resolve only, connections denied",
            tier=tier,
            hostname=hostname,
        )

    if cap == "localhost":
        if hostname in _LOCALHOST_NAMES:
            return NetworkDecision(
                allow=True,
                reason=f"tier {tier}: localhost allowed",
                tier=tier,
                hostname=hostname,
            )
        return NetworkDecision(
            allow=False,
            reason=f"tier {tier}: only localhost connections allowed",
            tier=tier,
            hostname=hostname,
        )

    if cap == "allowlist":
        # T3: check scope's network policy
        if network.policy == "unrestricted":
            return NetworkDecision(
                allow=True,
                reason=f"tier {tier}: network policy is unrestricted",
                tier=tier,
                hostname=hostname,
            )

        if network.policy == "allowlist":
            allow_match = _matches_host_pattern(hostname, network.allow)
            if allow_match is not None:
                return NetworkDecision(
                    allow=True,
                    reason=f"tier {tier}: hostname matches allow list pattern: {allow_match!r}",
                    tier=tier,
                    hostname=hostname,
                )
            return NetworkDecision(
                allow=False,
                reason=f"tier {tier}: hostname not in allow list",
                tier=tier,
                hostname=hostname,
            )

        if network.policy == "denylist":
            # Already checked deny list above, so if we get here it's allowed
            return NetworkDecision(
                allow=True,
                reason=f"tier {tier}: hostname not in deny list",
                tier=tier,
                hostname=hostname,
            )

    # cap == "full" (T4) — still respect explicit allowlist policy
    if network.policy == "allowlist" and network.allow:
        allow_match = _matches_host_pattern(hostname, network.allow)
        if allow_match is not None:
            return NetworkDecision(
                allow=True,
                reason=f"tier {tier}: hostname matches allow list pattern: {allow_match!r}",
                tier=tier,
                hostname=hostname,
            )
        return NetworkDecision(
            allow=False,
            reason=f"tier {tier}: hostname not in allow list",
            tier=tier,
            hostname=hostname,
        )

    return NetworkDecision(
        allow=True,
        reason=f"tier {tier}: full network access",
        tier=tier,
        hostname=hostname,
    )
