from consurg.scope import Scope


def generate_cursor_rules(scope: Scope) -> str:
    lines = [
        f"# Context Surgeon Scope: {scope.scope_name}",
        "#",
        "# File access restrictions are in effect.",
        "# Only interact with files listed below at their designated tier.",
        "",
    ]

    if scope.working_set:
        lines.append("# READ-WRITE (full access)")
        for p in scope.working_set:
            lines.append(f"allow: {p}")
        lines.append("")

    if scope.reference:
        lines.append("# READ-ONLY")
        for p in scope.reference:
            lines.append(f"read-only: {p}")
        lines.append("")

    if scope.signatures:
        lines.append("# SIGNATURE-ONLY")
        for p in scope.signatures:
            lines.append(f"signature: {p}")
        lines.append("")

    if scope.visible:
        lines.append("# EXISTENCE-ONLY")
        for p in scope.visible:
            lines.append(f"visible: {p}")
        lines.append("")

    lines.append("# All other files are BLOCKED.")
    lines.append("")
    return "\n".join(lines)
