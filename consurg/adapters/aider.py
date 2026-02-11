from consurg.scope import Scope


def generate_aider_args(scope: Scope) -> list[str]:
    args: list[str] = []
    for pattern in scope.working_set:
        args.extend(["--file", pattern])
    for pattern in scope.reference:
        args.extend(["--read", pattern])
    return args
