"""
algorithms.py
=============
Hand-written graph algorithms for the Intelligent Campus Navigation System.

    bfs(graph, source, target)        – Breadth-First Search  (QUEUE)
    dfs(graph, source, target)        – Depth-First Search    (STACK)
    dijkstra(graph, source, target)   – Dijkstra's algorithm  (MIN-HEAP)

`graph` is a plain adjacency-list dictionary:

    { "Academic Block": {"Library": 120, "Laboratory": 80, ...}, ... }

No graph library is used. Python's `collections.deque` is only used as a
FIFO queue, and `heapq` only as a binary-heap priority queue.

Every algorithm returns the same structured dictionary:

    {
        "algorithm": "BFS" | "DFS" | "Dijkstra",
        "source": ..., "target": ...,
        "found":     True/False,
        "path":      [source, ..., target]   (empty if not found),
        "edges":     number of edges in path,
        "distance":  total metres along path (inf if not found),
        "visited":   order in which vertices were VISITED / processed,
        "parents":   {vertex: parent}        (parent tracking),
        "distances": {vertex: best distance} (Dijkstra only, else {}),
        "steps":     list of snapshots of the data structures, used by the
                     UI for animation and by Explanation mode,
        "explore_events": ordered edge examinations (instrumentation only;
                     does not change the path),
        "time_ms":   execution time in milliseconds,
    }
"""

import heapq
import time
from collections import deque

INF = float("inf")


# =============================================================================
# Helper functions
# =============================================================================
def reconstruct_path(parents, source, target):
    """
    Walk backwards from target to source using the parent dictionary,
    then reverse the list.   parents[source] is None.
    Returns [] if the target was never reached.
    """
    if target not in parents:
        return []
    path = []
    node = target
    while node is not None:
        path.append(node)
        node = parents[node]
    path.reverse()
    return path if path and path[0] == source else []


def path_distance(graph, path):
    """Total weight of a path; INF if the path is empty."""
    if not path:
        return INF
    return sum(graph[path[i]][path[i + 1]] for i in range(len(path) - 1))


def _validate(graph, source, target):
    if source not in graph:
        raise KeyError(f"Unknown source vertex: {source}")
    if target not in graph:
        raise KeyError(f"Unknown target vertex: {target}")


def _tree_metres(graph, parents, node):
    """Weighted cost along the parent tree from the source to `node`."""
    if node not in parents:
        return INF
    cost, cur = 0, node
    while parents.get(cur) is not None:
        p = parents[cur]
        cost += graph[p][cur]
        cur = p
    return cost


def _explore_event(current, action, frontier, visited, parents, distances, edge,
                   weight=None, cum_cost=None, step=0):
    u, v = (edge if edge else (None, None))
    return {
        "current": current,
        "action": action,
        "frontier": frontier,
        "visited": visited,
        "parents": parents,
        "distances": distances,
        "edge": edge,
        "from": u,
        "to": v,
        "weight": weight,
        "cum_cost": cum_cost,
        "step": step,
    }


def _result(name, source, target, path, graph, visited, parents, distances, steps, t0,
            explore_events=None):
    found = bool(path)
    return {
        "algorithm": name,
        "source": source,
        "target": target,
        "found": found,
        "path": path,
        "edges": len(path) - 1 if found else 0,
        "distance": path_distance(graph, path) if found else INF,
        "visited": visited,
        "parents": parents,
        "distances": distances,
        "steps": steps,
        "explore_events": explore_events if explore_events is not None else [],
        "time_ms": (time.perf_counter() - t0) * 1000.0,
    }


# =============================================================================
# 1. BREADTH-FIRST SEARCH  –  O(V + E) time, O(V) space
# =============================================================================
def bfs(graph, source, target):
    """
    BFS explores the graph LEVEL BY LEVEL using a FIFO QUEUE.

    1. Put source in queue and mark it discovered.
    2. Remove the FIRST node from the queue (visit it).
    3. If it is the target -> stop.
    4. Add every undiscovered neighbour to the BACK of the queue,
       recording   parent[neighbour] = current.
    5. Repeat until the queue is empty.
    6. Reconstruct the path from the parent dictionary.

    BFS IGNORES edge weights: it finds the path with the MINIMUM NUMBER OF
    EDGES (hops). The distance in metres is only computed afterwards for
    display – BFS does not optimise it.
    """
    _validate(graph, source, target)
    t0 = time.perf_counter()

    queue = deque([source])          # FIFO queue
    discovered = {source}            # "marked visited" when enqueued
    parents = {source: None}         # parent tracking
    level = {source: 0}              # BFS level (= hops from source)
    visited = []                     # order of processing (dequeue order)
    steps = [{
        "current": None,
        "action": f"Initialise: enqueue {source}, mark it discovered.",
        "frontier": list(queue),
        "visited": [],
        "discovered": list(discovered),
        "parents": dict(parents),
        "distances": dict(level),
        "edge": None,
    }]
    explore_events = []
    step_id = 0

    while queue:
        current = queue.popleft()                    # remove FIRST element
        visited.append(current)
        step_id += 1

        if current == target:
            steps.append({
                "current": current,
                "action": f"Dequeue {current} – TARGET REACHED. Stop.",
                "frontier": list(queue), "visited": list(visited),
                "discovered": list(discovered), "parents": dict(parents),
                "distances": dict(level), "edge": None,
            })
            parent = parents.get(current)
            explore_events.append(_explore_event(
                current, "chosen", list(queue), list(visited), dict(parents),
                dict(level), (parent, current) if parent else None,
                weight=graph[parent][current] if parent else 0,
                cum_cost=_tree_metres(graph, parents, current), step=step_id))
            break

        added = []
        for neighbour, weight in graph[current].items():   # weight NOT used
            if neighbour not in discovered:
                discovered.add(neighbour)
                parents[neighbour] = current
                level[neighbour] = level[current] + 1
                queue.append(neighbour)              # add to BACK
                added.append(neighbour)
                explore_events.append(_explore_event(
                    current, "queued", list(queue), list(visited), dict(parents),
                    dict(level), (current, neighbour), weight=weight,
                    cum_cost=_tree_metres(graph, parents, neighbour), step=step_id))
            else:
                explore_events.append(_explore_event(
                    current, "visited", list(queue), list(visited), dict(parents),
                    dict(level), (current, neighbour), weight=weight,
                    cum_cost=_tree_metres(graph, parents, current), step=step_id))

        steps.append({
            "current": current,
            "action": (f"Dequeue {current} (level {level[current]}). "
                       + (f"Enqueue {', '.join(added)}." if added
                          else "No new neighbours.")),
            "frontier": list(queue), "visited": list(visited),
            "discovered": list(discovered), "parents": dict(parents),
            "distances": dict(level), "edge": None,
        })

    path = reconstruct_path(parents, source, target)
    return _result("BFS", source, target, path, graph, visited, parents, {}, steps, t0,
                   explore_events)


# =============================================================================
# 2. DEPTH-FIRST SEARCH  –  O(V + E) time, O(V) space
# =============================================================================
def dfs(graph, source, target):
    """
    DFS explores as DEEP as possible before BACKTRACKING, using an explicit
    LIFO STACK of (vertex, parent) pairs.

    1. Push (source, None) on the stack.
    2. Pop the TOP pair. If the vertex is already visited, skip it.
    3. Mark it visited and record its parent.
    4. If it is the target -> stop.
    5. Push all unvisited neighbours (in reverse order so that the first
       neighbour in the adjacency list is explored first).
    6. Repeat until the stack is empty.

    DFS does NOT guarantee the shortest route – it simply returns the first
    path it happens to find along its deep exploration.
    """
    _validate(graph, source, target)
    t0 = time.perf_counter()

    stack = [(source, None)]         # LIFO stack
    visited_set = set()
    parents = {}
    visited = []
    depth = {source: 0}
    steps = [{
        "current": None,
        "action": f"Initialise: push {source} on the stack.",
        "frontier": [v for v, _ in stack],
        "visited": [], "discovered": [source],
        "parents": {}, "distances": dict(depth), "edge": None,
    }]
    explore_events = []
    step_id = 0

    while stack:
        current, parent = stack.pop()                # remove TOP element
        step_id += 1
        if current in visited_set:
            steps.append({
                "current": current,
                "action": f"Pop {current} – already visited, backtrack.",
                "frontier": [v for v, _ in stack], "visited": list(visited),
                "discovered": list(visited_set), "parents": dict(parents),
                "distances": dict(depth), "edge": None,
            })
            continue

        visited_set.add(current)
        visited.append(current)
        parents[current] = parent
        if parent is not None:
            depth[current] = depth[parent] + 1

        if current == target:
            steps.append({
                "current": current,
                "action": f"Pop {current} – TARGET REACHED. Stop.",
                "frontier": [v for v, _ in stack], "visited": list(visited),
                "discovered": list(visited_set), "parents": dict(parents),
                "distances": dict(depth), "edge": (parent, current) if parent else None,
            })
            explore_events.append(_explore_event(
                current, "chosen", [v for v, _ in stack], list(visited), dict(parents),
                dict(depth), (parent, current) if parent else None,
                weight=graph[parent][current] if parent else 0,
                cum_cost=_tree_metres(graph, parents, current), step=step_id))
            break

        pushed = []
        for neighbour, weight in reversed(list(graph[current].items())):
            if neighbour not in visited_set:
                stack.append((neighbour, current))   # push on TOP
                pushed.append(neighbour)
                explore_events.append(_explore_event(
                    current, "queued", [v for v, _ in stack], list(visited),
                    dict(parents), dict(depth), (current, neighbour), weight=weight,
                    cum_cost=_tree_metres(graph, parents, current) + weight, step=step_id))
            else:
                explore_events.append(_explore_event(
                    current, "visited", [v for v, _ in stack], list(visited),
                    dict(parents), dict(depth), (current, neighbour), weight=weight,
                    cum_cost=_tree_metres(graph, parents, current), step=step_id))

        steps.append({
            "current": current,
            "action": (f"Pop {current} (depth {depth[current]}), mark visited. "
                       + (f"Push {', '.join(reversed(pushed))}." if pushed
                          else "Dead end – backtrack.")),
            "frontier": [v for v, _ in stack], "visited": list(visited),
            "discovered": list(visited_set), "parents": dict(parents),
            "distances": dict(depth), "edge": (parent, current) if parent else None,
        })

    path = reconstruct_path(parents, source, target)
    return _result("DFS", source, target, path, graph, visited, parents, {}, steps, t0,
                   explore_events)


# =============================================================================
# 3. DIJKSTRA'S ALGORITHM  –  O((V + E) log V) time, O(V + E) space
# =============================================================================
def dijkstra(graph, source, target):
    """
    Dijkstra finds the MINIMUM TOTAL DISTANCE path in a graph with
    non-negative edge weights, using a MIN-HEAP priority queue.

    1. dist[v] = infinity for every v;  dist[source] = 0.
    2. Push (0, source) into the priority queue.
    3. Extract the vertex u with the SMALLEST tentative distance.
       (Skip it if it was already finalised – "lazy deletion".)
    4. If u is the target -> stop; its distance is final.
    5. For each neighbour v of u:
           tentative = dist[u] + weight(u, v)
           if tentative < dist[v]:            (RELAXATION)
               dist[v]   = tentative
               parent[v] = u
               push (tentative, v)
    6. Reconstruct the shortest path using the parent dictionary.
    """
    _validate(graph, source, target)
    t0 = time.perf_counter()

    dist = {v: INF for v in graph}
    dist[source] = 0
    parents = {source: None}
    finalised = set()
    visited = []
    counter = 0                                  # tie-breaker for the heap
    pq = [(0, counter, source)]                  # (distance, order, vertex)

    def pq_state():
        return sorted((d, v) for d, _, v in pq)

    steps = [{
        "current": None,
        "action": f"Initialise: dist[{source}] = 0, all others = ∞. Push {source}.",
        "frontier": pq_state(), "visited": [], "discovered": [source],
        "parents": dict(parents), "distances": dict(dist), "edge": None,
    }]
    explore_events = []
    step_id = 0

    while pq:
        d, _, u = heapq.heappop(pq)              # extract-min
        step_id += 1
        if u in finalised:
            steps.append({
                "current": u,
                "action": f"Pop ({d}, {u}) – stale entry, already finalised. Skip.",
                "frontier": pq_state(), "visited": list(visited),
                "discovered": list(parents), "parents": dict(parents),
                "distances": dict(dist), "edge": None,
            })
            continue

        finalised.add(u)
        visited.append(u)

        if u == target:
            steps.append({
                "current": u,
                "action": f"Extract {u} with dist {d} – TARGET finalised. Stop.",
                "frontier": pq_state(), "visited": list(visited),
                "discovered": list(parents), "parents": dict(parents),
                "distances": dict(dist), "edge": None,
            })
            parent = parents.get(u)
            explore_events.append(_explore_event(
                u, "chosen", pq_state(), list(visited), dict(parents), dict(dist),
                (parent, u) if parent else None,
                weight=graph[parent][u] if parent else 0,
                cum_cost=dist[u], step=step_id))
            break

        relaxed = []
        for v, w in graph[u].items():
            if v in finalised:
                explore_events.append(_explore_event(
                    u, "visited", pq_state(), list(visited), dict(parents), dict(dist),
                    (u, v), weight=w, cum_cost=dist[u], step=step_id))
                continue
            tentative = dist[u] + w
            if tentative < dist[v]:               # relaxation
                old = dist[v]
                dist[v] = tentative
                parents[v] = u
                counter += 1
                heapq.heappush(pq, (tentative, counter, v))
                relaxed.append(f"{v}: {'∞' if old == INF else old}→{tentative}")
                explore_events.append(_explore_event(
                    u, "relaxed", pq_state(), list(visited), dict(parents), dict(dist),
                    (u, v), weight=w, cum_cost=tentative, step=step_id))
            else:
                explore_events.append(_explore_event(
                    u, "examined", pq_state(), list(visited), dict(parents), dict(dist),
                    (u, v), weight=w, cum_cost=dist[v], step=step_id))

        steps.append({
            "current": u,
            "action": (f"Extract {u} (dist {d}). "
                       + (f"Relax {'; '.join(relaxed)}." if relaxed
                          else "No distance improved.")),
            "frontier": pq_state(), "visited": list(visited),
            "discovered": list(parents), "parents": dict(parents),
            "distances": dict(dist), "edge": None,
        })

    path = reconstruct_path(parents, source, target) if target in finalised else []
    return _result("Dijkstra", source, target, path, graph, visited, parents,
                   dict(dist), steps, t0, explore_events)


# Registry used by the navigation controller / UI
ALGORITHMS = {
    "BFS": bfs,
    "DFS": dfs,
    "Dijkstra": dijkstra,
}

COMPLEXITY = {
    "BFS": {"time": "O(V + E)", "space": "O(V)", "structure": "Queue (FIFO)"},
    "DFS": {"time": "O(V + E)", "space": "O(V)", "structure": "Stack (LIFO)"},
    "Dijkstra": {"time": "O((V + E) log V)", "space": "O(V + E)",
                 "structure": "Priority Queue (Binary Min-Heap)"},
}
