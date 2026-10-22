"""
navigation.py
=============
NAVIGATION CONTROLLER – the layer between the user interface and the
algorithms.  The UI never calls bfs/dfs/dijkstra directly; it asks the
controller, which:

    * validates the user's selection,
    * builds the ACTIVE graph (original graph minus blocked roads),
    * runs the requested algorithm,
    * detects blocked routes and finds alternatives,
    * produces BFS-vs-Dijkstra comparisons.
"""

from algorithms import ALGORITHMS, INF, bfs, dfs, dijkstra, path_distance
from graph import build_campus_graph, edge_key

# Error / status messages (exact wording from the specification)
MSG_SAME = "Source and destination cannot be the same."
MSG_NO_ROUTE = "No route available between selected locations."
MSG_SELECT = "Please select both source and destination."
MSG_NO_ALT = "No alternative simple route exists between these buildings."


def fmt_alt_delta(extra):
    if extra == 0:
        return "same distance"
    if extra > 0:
        return f"+{extra:g} m longer"
    return f"{extra:g} m shorter"


def path_edges(path):
    """Set of undirected edge keys used by a path."""
    return {edge_key(path[i], path[i + 1]) for i in range(len(path) - 1)}


class NavigationController:
    def __init__(self, graph=None):
        self.graph = graph if graph is not None else build_campus_graph()

    # ------------------------------------------------------------ validation
    def validate(self, source, target):
        """Return an error message, or None if the selection is valid."""
        if not source or not target:
            return MSG_SELECT
        if source not in self.graph.adjacency or target not in self.graph.adjacency:
            return MSG_SELECT
        if source == target:
            return MSG_SAME
        return None

    # ------------------------------------------------------------ main route
    def find_route(self, source, target, algorithm):
        """
        Run `algorithm` on the ACTIVE graph (blocked roads removed).

        Also runs it on the ORIGINAL graph: if the original route used a
        blocked road, the result is flagged as an automatic alternative.

        Returns dict:
            ok, error, status ('found' | 'rerouted' | 'none'),
            message, result, original (result on unblocked graph or None),
            blocked_on_route (list of blocked edges the original used)
        """
        err = self.validate(source, target)
        if err:
            return {"ok": False, "error": err, "status": "error", "message": err}

        func = ALGORITHMS[algorithm]
        active = self.graph.full_view()
        result = func(active, source, target)

        original, blocked_on_route = None, []
        if self.graph.blocked:
            original = func(self.graph.full_view(), source, target)
            if original["found"]:
                blocked_on_route = sorted(path_edges(original["path"]) & self.graph.blocked)

        if not result["found"]:
            msg = MSG_NO_ALT if blocked_on_route else MSG_NO_ROUTE
            return {"ok": True, "error": None, "status": "none", "message": msg,
                    "result": result, "original": original,
                    "blocked_on_route": blocked_on_route}

        if blocked_on_route:
            status = "rerouted"
            message = "Route blocked – alternative route found automatically."
        else:
            status = "found"
            message = {
                "BFS": "Minimum-edge route found (BFS ignores distances).",
                "DFS": "Route found by DFS (not guaranteed to be shortest).",
                "Dijkstra": "Shortest weighted route found.",
            }[algorithm]
        return {"ok": True, "error": None, "status": status, "message": message,
                "result": result, "original": original,
                "blocked_on_route": blocked_on_route}

    # ------------------------------------------------------ alternative route
    def second_shortest_route(self, adjacency, source, target, primary_path, func):
        """
        Next-best SIMPLE route that differs from `primary_path`.
        For each edge on the best route, run `func` on a COPY of the graph
        without that edge (the real graph is never mutated) and keep the
        cheapest distinct result.
        """
        best = None
        for (u, v) in [(primary_path[i], primary_path[i + 1])
                       for i in range(len(primary_path) - 1)]:
            reduced = {a: dict(nbrs) for a, nbrs in adjacency.items()}
            reduced[u].pop(v, None)
            reduced[v].pop(u, None)
            res = func(reduced, source, target)
            if res["found"] and res["path"] != primary_path:
                better = (best is None
                          or res["distance"] < best["distance"]
                          or (res["distance"] == best["distance"]
                              and res["edges"] < best["edges"]))
                if better:
                    best = res
                    best["removed_edge"] = (u, v)
        return best

    def find_alternative(self, source, target, algorithm="Dijkstra"):
        """Second-best simple route for the selected algorithm."""
        err = self.validate(source, target)
        if err:
            return {"ok": False, "error": err, "status": "error", "message": err}

        func = ALGORITHMS[algorithm]
        full = self.graph.full_view()
        primary = func(full, source, target)
        if not primary["found"]:
            return {"ok": True, "status": "none", "message": MSG_NO_ROUTE,
                    "primary": primary, "alternative": None, "blocked_on_route": [],
                    "mode": None, "algorithm": algorithm}

        alt = self.second_shortest_route(full, source, target, primary["path"], func)
        mode = "second_best"
        if alt is None:
            return {"ok": True, "status": "none",
                    "message": "No alternative simple route exists between these buildings.",
                    "primary": primary, "alternative": None,
                    "blocked_on_route": [], "mode": mode, "algorithm": algorithm}
        extra = alt["distance"] - primary["distance"]
        message = (f"Second-best {algorithm} route found "
                   f"({fmt_alt_delta(extra)} vs the best route).")
        return {"ok": True, "status": "found", "message": message,
                "primary": primary, "alternative": alt,
                "blocked_on_route": [], "mode": mode,
                "extra_distance": extra, "algorithm": algorithm}

    # ------------------------------------------------------------ comparison
    def compare(self, source, target):
        """Run BFS, DFS and Dijkstra on the current graph."""
        err = self.validate(source, target)
        if err:
            return {"ok": False, "error": err}
        active = self.graph.full_view()
        b = bfs(active, source, target)
        f = dfs(active, source, target)
        d = dijkstra(active, source, target)
        return {"ok": True, "bfs": b, "dfs": f, "dijkstra": d,
                "same_path": b["path"] == d["path"]}

    def disagreement_example(self, preferred=("Academic Block", "Medical Centre")):
        """
        Find a source/destination pair where BFS (fewest edges) and
        Dijkstra (least distance) choose DIFFERENT routes on the ORIGINAL
        graph – used by the "Weighted vs Unweighted" explanation.
        """
        full = self.graph.full_view()

        def check(s, t):
            b, d = bfs(full, s, t), dijkstra(full, s, t)
            if b["found"] and d["found"] and b["distance"] > d["distance"]:
                return {"source": s, "target": t, "bfs": b, "dijkstra": d}
            return None

        if preferred[0] in full and preferred[1] in full:
            ex = check(*preferred)
            if ex:
                return ex
        best = None
        for s in full:
            for t in full:
                if s != t:
                    ex = check(s, t)
                    if ex and (best is None or
                               ex["bfs"]["distance"] - ex["dijkstra"]["distance"] >
                               best["bfs"]["distance"] - best["dijkstra"]["distance"]):
                        best = ex
        return best

    # ------------------------------------------------------------ blocking
    def block_road(self, u, v):
        self.graph.block_edge(u, v)

    def unblock_road(self, u, v):
        self.graph.unblock_edge(u, v)

    def restore_roads(self):
        self.graph.restore_all()

    def blocked_roads(self):
        return sorted(self.graph.blocked)

    # ------------------------------------------------------------ info
    def connections(self, node):
        """[(neighbour, weight, is_blocked), ...] for the map click panel."""
        return [(v, w, self.graph.is_blocked(node, v))
                for v, w in self.graph.neighbours(node, include_blocked=True)]

    def graph_info(self):
        return {
            "nodes": self.graph.num_vertices(),
            "edges": self.graph.num_edges(),
            "blocked": len(self.graph.blocked),
            "type": "Weighted Undirected Graph",
            "representation": "Adjacency List",
            "algorithms": ["BFS", "DFS", "Dijkstra"],
        }

    def distance_of(self, path):
        return path_distance(self.graph.full_view(), path) if path else INF
