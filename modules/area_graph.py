"""Room adjacency graph — standalone, no networkx dependency.

Loads connections.yml and provides graph queries for occupancy tracking and
area scope resolution. Pure dict of sets — no external dependencies beyond
the yaml module already present in the pyscript environment.
"""

from __future__ import annotations

import os
import yaml

try:
    from modules.logger import Logger
except ImportError:
    from logger import Logger

log = Logger(__name__, globals().get("log"))


def load_connections(path: str) -> list[dict[str, str]]:
    """Load the connections list from a YAML file.

    The file format expects a top-level ``connections`` key whose value is a
    list of single-key dicts, e.g.::

        connections:
          - bedroom: hallway
          - hallway: kitchen

    Returns an empty list if the path doesn't exist so that consumers don't
    need to guard against missing config during development.
    """
    if not os.path.exists(path):
        log.warning(f"AreaGraph: connections file not found: {path}")
        return []
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    return data.get("connections", [])


class AreaGraph:
    """Undirected graph of area connections.

    Parameters
    ----------
    source : str or list[dict[str, str]]
        Either a path to a YAML file or an already-parsed connections list.
    """

    def __init__(self, source: str | list[dict[str, str]]) -> None:
        if isinstance(source, str):
            connection_pairs = load_connections(source)
        else:
            connection_pairs = source

        self._adj: dict[str, set[str]] = {}
        for pair in connection_pairs:
            for a, b in pair.items():
                self._adj.setdefault(a, set()).add(b)
                self._adj.setdefault(b, set()).add(a)

        log.info(
            f"AreaGraph: loaded {len(self._adj)} areas, "
            f"{len(connection_pairs)} edges"
        )

    # -- Public queries -------------------------------------------------------

    def neighbors(self, area: str) -> set[str]:
        """Areas directly connected to *area*.

        Returns an empty set when *area* is unknown rather than raising.
        """
        return self._adj.get(area, set())

    def distance(self, a: str, b: str) -> int:
        """Shortest path length between *a* and *b* (BFS).

        Returns ``-1`` if there is no path.
        """
        if a == b:
            return 0
        if a not in self._adj or b not in self._adj:
            return -1

        visited: set[str] = set()
        queue: list[tuple[str, int]] = [(a, 0)]
        visited.add(a)
        while queue:
            current, dist = queue.pop(0)
            for neighbor in self._adj[current]:
                if neighbor == b:
                    return dist + 1
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, dist + 1))
        return -1

    def connected_areas(self, area: str) -> set[str]:
        """All areas reachable from *area* (transitive closure).

        Includes *area* itself. Returns empty set if *area* is unknown.
        """
        if area not in self._adj:
            return set()
        visited: set[str] = set()
        stack = [area]
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            for neighbor in self._adj[current]:
                if neighbor not in visited:
                    stack.append(neighbor)
        return visited

    def has_area(self, area: str) -> bool:
        """Is *area* a known node in the graph?"""
        return area in self._adj

    @property
    def areas(self) -> set[str]:
        """All known area names."""
        return set(self._adj.keys())

    def __contains__(self, area: str) -> bool:
        return area in self._adj

    def __len__(self) -> int:
        return len(self._adj)

    def __repr__(self) -> str:
        return f"AreaGraph({len(self._adj)} areas)"
