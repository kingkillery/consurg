from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto


class DependencyKind(Enum):
    IMPORT = auto()
    RE_EXPORT = auto()
    TYPE_ONLY = auto()


@dataclass
class _Edge:
    target: str
    kind: DependencyKind


class DependencyGraph:
    def __init__(self):
        self._forward: dict[str, list[_Edge]] = {}
        self._reverse: dict[str, list[_Edge]] = {}
        self._nodes: set[str] = set()

    def add_edge(self, source: str, target: str, kind: DependencyKind):
        self._nodes.add(source)
        self._nodes.add(target)
        self._forward.setdefault(source, []).append(_Edge(target=target, kind=kind))
        self._reverse.setdefault(target, []).append(_Edge(target=source, kind=kind))

    def get_dependencies(self, file: str) -> set[str]:
        return {e.target for e in self._forward.get(file, [])}

    def get_dependents(self, file: str) -> set[str]:
        return {e.target for e in self._reverse.get(file, [])}

    def classify_tiers(self, entry_files: list[str]) -> dict[str, int]:
        tiers: dict[str, int] = {}

        for f in entry_files:
            if f in self._nodes:
                tiers[f] = 4

        # BFS from entry files to find direct and transitive deps
        direct: set[str] = set()
        for f in entry_files:
            for dep in self.get_dependencies(f):
                if dep not in tiers:
                    direct.add(dep)

        for d in direct:
            tiers[d] = 3

        # BFS for transitive deps (depth >= 2)
        queue: deque[str] = deque(direct)
        visited = set(tiers.keys())

        while queue:
            current = queue.popleft()
            for dep in self.get_dependencies(current):
                if dep not in visited:
                    visited.add(dep)
                    tiers[dep] = 2
                    queue.append(dep)

        # Everything else in the graph is tier 1
        for node in self._nodes:
            if node not in tiers:
                tiers[node] = 1

        return tiers
