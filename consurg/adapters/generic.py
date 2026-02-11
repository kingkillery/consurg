from consurg.scope import Scope


def generate_generic_prompt(scope: Scope) -> str:
    lines = [
        f"[SCOPE: {scope.scope_name}]",
        "",
        "You are restricted to the following file access tiers:",
        "",
    ]

    tier_map = [
        ("Tier 4 - READ-WRITE", scope.working_set),
        ("Tier 3 - READ-ONLY", scope.reference),
        ("Tier 2 - SIGNATURE", scope.signatures),
        ("Tier 1 - EXISTENCE", scope.visible),
    ]

    for label, patterns in tier_map:
        if patterns:
            lines.append(f"{label}:")
            for p in patterns:
                lines.append(f"  {p}")
            lines.append("")

    lines.append("Tier 0 - BLOCKED: All files not listed above.")
    lines.append("Do not access blocked files under any circumstances.")
    lines.append("")
    return "\n".join(lines)
