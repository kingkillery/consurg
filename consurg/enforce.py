from consurg.scope import Scope, pattern_matches


def resolve_tier_with_pattern(
    file_path: str, scope: Scope
) -> tuple[int, str, str | None]:
    for pattern in scope.working_set:
        if pattern_matches(file_path, pattern):
            return (4, "READ-WRITE", pattern)
    for pattern in scope.reference:
        if pattern_matches(file_path, pattern):
            return (3, "READ-ONLY", pattern)
    for pattern in scope.signatures:
        if pattern_matches(file_path, pattern):
            return (2, "SIGNATURE", pattern)
    for pattern in scope.visible:
        if pattern_matches(file_path, pattern):
            return (1, "EXISTENCE", pattern)
    return (0, "BLOCKED", None)


def resolve_tier(file_path: str, scope: Scope) -> tuple[int, str]:
    tier, label, _ = resolve_tier_with_pattern(file_path, scope)
    return (tier, label)
