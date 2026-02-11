from consurg.scope import Scope


def generate_claude_scope(scope: Scope) -> str:
    lines = [
        f"# Context Surgeon Scope: {scope.scope_name}",
        "",
        "This scope restricts which files you may access. Obey these restrictions.",
        "",
    ]

    sections = [
        ("## Working Set (READ-WRITE)", scope.working_set),
        ("## Reference (READ-ONLY)", scope.reference),
        ("## Signatures (SIGNATURE-ONLY)", scope.signatures),
        ("## Visible (EXISTENCE-ONLY)", scope.visible),
    ]

    for heading, patterns in sections:
        if patterns:
            lines.append(heading)
            lines.append("")
            for p in patterns:
                lines.append(f"- `{p}`")
            lines.append("")

    lines.append("All other files are **BLOCKED**. Do not read, write, or reference them.")
    lines.append("")
    return "\n".join(lines)
