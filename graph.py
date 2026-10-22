"""
graph.py
========
Weighted, undirected graph stored as an ADJACENCY LIST.

    adjacency = {
        "Academic Block": {"Library": 120, "Laboratory": 80, ...},
        "Library":        {"Academic Block": 120, "Cafeteria": 100, ...},
        ...
    }

Each vertex maps to a dictionary of {neighbour: edge_weight}.
Because the graph is undirected, every edge (u, v, w) is stored twice:
    adjacency[u][v] = w   and   adjacency[v][u] = w

Blocked roads are kept in a separate set so that a road can be
"temporarily removed" for routing and later restored without losing data.
"""


def edge_key(u, v):
    """Order-independent key for an undirected edge."""
    return tuple(sorted((u, v)))


class CampusGraph:
    """Weighted undirected graph using an adjacency list."""

    def __init__(self):
        self.adjacency = {}          # vertex -> {neighbour: weight}
        self.blocked = set()         # set of edge_key(u, v)

    # ------------------------------------------------------------------ build
    def add_vertex(self, v):
        if v not in self.adjacency:
            self.adjacency[v] = {}

    def add_edge(self, u, v, weight):
        """Add an undirected weighted edge u <-> v."""
        if weight < 0:
            raise ValueError("Edge weights must be non-negative (required by Dijkstra).")
        self.add_vertex(u)
        self.add_vertex(v)
        self.adjacency[u][v] = weight
        self.adjacency[v][u] = weight

    @classmethod
    def from_edges(cls, vertices, edges):
        g = cls()
        for v in vertices:
            g.add_vertex(v)
        for u, v, w in edges:
            g.add_edge(u, v, w)
        return g

    # ------------------------------------------------------------------ query
    @property
    def vertices(self):
        return list(self.adjacency.keys())

    def edges(self):
        """Each undirected edge exactly once as (u, v, w) – in insertion order."""
        seen, result = set(), []
        for u, nbrs in self.adjacency.items():
            for v, w in nbrs.items():
                k = edge_key(u, v)
                if k not in seen:
                    seen.add(k)
                    result.append((u, v, w))
        return result

    def num_vertices(self):
        return len(self.adjacency)

    def num_edges(self):
        return len(self.edges())

    def has_edge(self, u, v):
        return v in self.adjacency.get(u, {})

    def weight(self, u, v):
        return self.adjacency[u][v]

    def neighbours(self, u, include_blocked=False):
        """
        Neighbours of u as an ordered list of (v, weight).
        Blocked roads are skipped unless include_blocked=True.
        """
        result = []
        for v, w in self.adjacency.get(u, {}).items():
            if include_blocked or edge_key(u, v) not in self.blocked:
                result.append((v, w))
        return result

    # --------------------------------------------------------------- blocking
    def block_edge(self, u, v):
        if not self.has_edge(u, v):
            raise KeyError(f"No road between {u} and {v}.")
        self.blocked.add(edge_key(u, v))

    def unblock_edge(self, u, v):
        self.blocked.discard(edge_key(u, v))

    def restore_all(self):
        self.blocked.clear()

    def is_blocked(self, u, v):
        return edge_key(u, v) in self.blocked

    def active_view(self):
        """
        Return a NEW plain adjacency dict with blocked edges removed.
        This is what the algorithms operate on – the original graph is
        never modified, so roads can always be restored.
        """
        return {u: dict(self.neighbours(u)) for u in self.adjacency}

    def full_view(self):
        """Adjacency dict including blocked edges (original campus)."""
        return {u: dict(nbrs) for u, nbrs in self.adjacency.items()}

    def path_distance(self, path):
        """Sum of edge weights along a path (uses original weights)."""
        return sum(self.adjacency[path[i]][path[i + 1]] for i in range(len(path) - 1))

    def __repr__(self):
        lines = []
        for u, nbrs in self.adjacency.items():
            inner = ", ".join(f"{v}: {w}" for v, w in nbrs.items())
            lines.append(f"{u} -> {{{inner}}}")
        return "\n".join(lines)


def build_campus_graph():
    """Create the campus graph from campus_data.py."""
    from campus_data import LOCATION_ORDER, get_roads
    return CampusGraph.from_edges(LOCATION_ORDER, get_roads())
