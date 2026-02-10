from consurg.enforce import resolve_tier
from consurg.scope import Scope


def _scope(**kwargs) -> Scope:
    return Scope(**kwargs)


def test_exact_match_working_set():
    scope = _scope(working_set=["src/main.py"])
    assert resolve_tier("src/main.py", scope) == (4, "READ-WRITE")


def test_glob_match():
    scope = _scope(reference=["*.py"])
    assert resolve_tier("utils.py", scope) == (3, "READ-ONLY")


def test_nested_glob():
    scope = _scope(signatures=["**/*.py"])
    assert resolve_tier("deep/nested/module.py", scope) == (2, "SIGNATURE")


def test_priority_ordering():
    scope = _scope(
        working_set=["src/main.py"],
        visible=["src/*.py"],
    )
    tier, label = resolve_tier("src/main.py", scope)
    assert tier == 4
    assert label == "READ-WRITE"


def test_unmatched_returns_blocked():
    scope = _scope(working_set=["src/*.py"])
    assert resolve_tier("other/file.txt", scope) == (0, "BLOCKED")


def test_visible_tier():
    scope = _scope(visible=["config/*"])
    assert resolve_tier("config/settings.json", scope) == (1, "EXISTENCE")
