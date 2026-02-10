from fnmatch import fnmatch

from consurg.scope import Scope


def resolve_tier(file_path: str, scope: Scope) -> tuple[int, str]:
    for pattern in scope.working_set:
        if fnmatch(file_path, pattern):
            return (4, "READ-WRITE")
    for pattern in scope.reference:
        if fnmatch(file_path, pattern):
            return (3, "READ-ONLY")
    for pattern in scope.signatures:
        if fnmatch(file_path, pattern):
            return (2, "SIGNATURE")
    for pattern in scope.visible:
        if fnmatch(file_path, pattern):
            return (1, "EXISTENCE")
    return (0, "BLOCKED")
