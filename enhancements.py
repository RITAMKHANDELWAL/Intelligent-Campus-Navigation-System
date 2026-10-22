"""
enhancements.py
===============
ADD-ON LAYER for the Intelligent Campus Navigation System (prompt 2).

This module is purely ADDITIVE. It never edits graph data, algorithms or
existing widgets. It integrates by SUBSCRIBING to existing methods: each
hooked method of ui.CampusNavigationApp / ui.MapCanvas is wrapped so that
the original runs first and the add-on reacts afterwards.

    install_enhancements()   – call once BEFORE creating the app (main.py)

Features (each can be switched off in FEATURES):
    A  map_labels    readable label chips offset from the node markers
       status_strip  status bar in the dark strip above the map
       metrics       live metrics (visited, edges, frontier size, cost)
    B  pseudocode    pseudocode card with the executing line highlighted
       dist_table    distance / visit table with flashing relaxations
       adjacency     adjacency list (Graph tab) with the current node marked
    C  why_not       "Why not the others?" lines in the Compare tab
    D  robustness    cancel stale animations on selection / algorithm change
    E  race          RACE ALL 3 in the Compare tab (own overlay layer)

All widgets created here live in their own containers and every attribute
is namespaced under `app.enh` (instance of `Enhancements`).
"""

import tkinter as tk

import customtkinter as ctk

import ui
from ui import FONT, MONO, ROUTE_COLORS
from utils import COLORS, fmt_distance, short

INF = float("inf")

# ---------------------------------------------------------------- feature flags
FEATURES = {
    "map_labels": True,
    "status_strip": True,
    "metrics": True,
    "pseudocode": True,
    "dist_table": True,
    "adjacency": True,
    "why_not": True,
    "robustness": True,
    "race": True,
}

# ---------------------------------------------------------------- style namespace
ENH = {
    "strip": "#0B1F3A",
    "chip": "#132D52",
    "key": "#93C5FD",
    "val": "#F8FAFC",
    "idle": "#94A3B8",
    "exploring": "#FACC15",
    "drawing": "#38BDF8",
    "done": "#4ADE80",
    "hl": "#FEF3C7",
    "hl_fg": "#7C2D12",
    "hl2": "#F1F5F9",
    "flash": "#FDE047",
    "final": "#DCFCE7",
    "current": "#FFEDD5",
    "card": "#F8FAFC",
}

# Visual-only label offsets (ORIGINAL image pixels, relative to the node).
# The graph coordinates in campus_data.NODE_POSITIONS are NOT changed; only a
# readable name chip is drawn next to the marker, on the side free of roads.
LABEL_OFFSETS = {
    "Library": (74, 0),
    "Academic Block": (0, 38),
    "Cafeteria": (-76, 0),
    "Parking": (82, 0),
    "Laboratory": (0, 40),
    "Medical Centre": (6, 40),
}

PSEUDOCODE = {
    "BFS": [
        "queue ← [source]; mark source discovered",
        "while queue is not empty:",
        "    u ← queue.dequeue()            # FIFO",
        "    if u = target: stop",
        "    for each neighbour v of u:",
        "        if v not discovered:",
        "            mark v; parent[v] ← u",
        "            queue.enqueue(v)",
        "path ← follow parent[] back from target",
    ],
    "DFS": [
        "stack ← [(source, None)]",
        "while stack is not empty:",
        "    (u, p) ← stack.pop()           # LIFO",
        "    if u visited: continue  (backtrack)",
        "    mark u visited; parent[u] ← p",
        "    if u = target: stop",
        "    for each neighbour v of u (reversed):",
        "        if v not visited: stack.push((v, u))",
        "path ← follow parent[] back from target",
    ],
    "Dijkstra": [
        "dist[*] ← ∞;  dist[source] ← 0",
        "heap ← [(0, source)]",
        "while heap is not empty:",
        "    (d, u) ← heap.extract_min()",
        "    if u finalised: continue  (stale)",
        "    finalise u;  if u = target: stop",
        "    for each neighbour v of u:",
        "        if dist[u] + w(u,v) < dist[v]:",
        "            dist[v] ← dist[u] + w;  parent[v] ← u",
        "            heap.push((dist[v], v))",
        "path ← follow parent[] back from target",
    ],
}

FRONTIER_NAME = {"BFS": "Queue", "DFS": "Stack", "Dijkstra": "Heap"}


# =============================================================================
# Pure helpers (no UI) – easy to unit-test
# =============================================================================
def tree_metres(adj, parents, node):
    """Metres from the source to `node` along the parent tree (INF if unknown)."""
    if node is None or node not in parents:
        return INF
    cost, cur, guard = 0, node, 0
    while parents.get(cur) is not None and guard <= len(parents):
        p = parents[cur]
        cost += adj[p][cur]
        cur, guard = p, guard + 1
    return cost


def step_metrics(res, i, adj):
    """Live metrics for step i of an algorithm result."""
    steps = res["steps"]
    i = max(0, min(i, len(steps) - 1))
    step = steps[i]
    events = res.get("explore_events", [])
    examined = sum(1 for e in events if e["step"] <= i and e["action"] != "chosen")
    relaxed = sum(1 for e in events if e["step"] <= i and e["action"] == "relaxed")
    cur = step["current"]
    if i == len(steps) - 1 and res["found"]:
        cost = res["distance"]
    elif cur is None:
        cost = 0
    elif res["algorithm"] == "Dijkstra":
        cost = step["distances"].get(cur, INF)
    else:
        cost = tree_metres(adj, step["parents"], cur)
    return {"visited": len(step["visited"]), "examined": examined, "relaxed": relaxed,
            "frontier": len(step["frontier"]), "cost": cost}


def pseudo_lines(algo, step, done=False):
    """(primary_line, {secondary lines}) – 1-based line numbers to highlight."""
    a = step["action"] if step else ""
    n = len(PSEUDOCODE[algo])
    if done:
        return n, set()
    if step is None:
        return None, set()
    if algo == "BFS":
        if a.startswith("Initialise"):
            return 1, set()
        if "TARGET" in a:
            return 4, {3}
        if "Enqueue" in a:
            return 8, {3, 5, 6, 7}
        return 6, {3, 5}
    if algo == "DFS":
        if a.startswith("Initialise"):
            return 1, set()
        if "already visited" in a:
            return 4, {3}
        if "TARGET" in a:
            return 6, {3, 5}
        if "Push" in a:
            return 8, {3, 5, 7}
        return 7, {3, 5}
    # Dijkstra
    if a.startswith("Initialise"):
        return 1, {2}
    if "stale" in a:
        return 5, {4}
    if "TARGET" in a:
        return 6, {4}
    if "Relax" in a:
        return 9, {4, 6, 7, 8, 10}
    return 8, {4, 6, 7}


def why_not_lines(resp):
    """
    "Why not the others?" explanation generated from real results.
    resp = NavigationController.compare(...) dict (bfs / dfs / dijkstra).
    Returns (winner_line, [lines for the other algorithms]).
    """
    res = {"BFS": resp.get("bfs"), "DFS": resp.get("dfs"), "Dijkstra": resp.get("dijkstra")}
    found = {k: r for k, r in res.items() if r and r["found"]}
    if not found:
        return "No route exists between these locations – no algorithm can win.", []
    best = min(r["distance"] for r in found.values())
    # Dijkstra is the guaranteed optimum; prefer it when tied.
    winner = "Dijkstra" if res["Dijkstra"] and res["Dijkstra"]["found"] \
        and res["Dijkstra"]["distance"] == best else min(found, key=lambda k: found[k]["distance"])
    w = found[winner]
    win_line = (f"Winner: {winner} – {fmt_distance(w['distance'])}, {w['edges']} hops, "
                f"{len(w['visited'])} nodes visited"
                + (" (guaranteed shortest on non-negative weights)." if winner == "Dijkstra" else "."))
    lines = []
    for name in ("BFS", "DFS", "Dijkstra"):
        if name == winner:
            continue
        r = res[name]
        if not r or not r["found"]:
            lines.append((name, f"{name}: no route found."))
            continue
        extra = r["distance"] - best
        tie = extra == 0
        if name == "BFS":
            if tie:
                txt = (f"BFS: {r['edges']} hops, {fmt_distance(r['distance'])} – TIES the winner here. "
                       f"It counts edges and ignores road length, so the tie is luck of this map, "
                       f"not a guarantee.")
            else:
                fewer = " (fewer hops!)" if r["edges"] < w["edges"] else ""
                txt = (f"BFS: {r['edges']} hops{fewer} but {fmt_distance(r['distance'])} "
                       f"(+{extra:g} m) – it counts edges and ignores road length.")
        elif name == "DFS":
            if tie:
                txt = (f"DFS: first path found, {fmt_distance(r['distance'])}, {r['edges']} hops – "
                       f"TIES the winner here, but only by chance: DFS has no optimality guarantee.")
            else:
                txt = (f"DFS: first path found, {fmt_distance(r['distance'])} (+{extra:g} m), "
                       f"{r['edges']} hops – it dives deep and has no optimality guarantee.")
        else:
            txt = (f"Dijkstra: {fmt_distance(r['distance'])} – ties the winner." if tie else
                   f"Dijkstra: {fmt_distance(r['distance'])}.")
        lines.append((name, txt))
    return win_line, lines


# =============================================================================
# Small widget helper
# =============================================================================
class Collapsible:
    """Card with a clickable header that shows / hides its body."""

    def __init__(self, master, title, expanded=True):
        self.title = title
        self.expanded = expanded
        self.frame = ctk.CTkFrame(master, fg_color=ENH["card"], corner_radius=10, border_width=1,
                                  border_color=COLORS["border"])
        self.head = ctk.CTkButton(self.frame, text="", anchor="w", height=26, corner_radius=8,
                                  font=(FONT, 11, "bold"), fg_color="transparent",
                                  text_color=COLORS["navy"], hover_color="#E2E8F0",
                                  command=self.toggle)
        self.head.pack(fill="x", padx=4, pady=(4, 2))
        self.body = ctk.CTkFrame(self.frame, fg_color="transparent")
        if expanded:
            self.body.pack(fill="x", padx=8, pady=(0, 8))
        self.set_title(title)

    def set_title(self, title):
        self.title = title
        self.head.configure(text=("▾  " if self.expanded else "▸  ") + title)

    def toggle(self):
        self.expanded = not self.expanded
        if self.expanded:
            self.body.pack(fill="x", padx=8, pady=(0, 8))
        else:
            self.body.pack_forget()
        self.set_title(self.title)


# =============================================================================
# The add-on controller (one per app window)
# =============================================================================
class Enhancements:
    def __init__(self, app):
        self.app = app
        self.reset_flag = True        # True after Reset / Clear (metrics show idle)
        self.note = None              # optional phase override text
        self._jobs = {}               # name -> after id (all cancellable)
        self._flash_jobs = []
        self.race = None
        if FEATURES["status_strip"] or FEATURES["metrics"]:
            self._build_strip()
        if FEATURES["pseudocode"]:
            self._build_pseudocode()
        if FEATURES["dist_table"]:
            self._build_table()
        if FEATURES["adjacency"]:
            self._build_adjacency()
        if FEATURES["why_not"] or FEATURES["race"]:
            self._build_compare_extra()
        self.sync()

    # ------------------------------------------------------------ timers
    def _after(self, name, ms, fn):
        self._cancel(name)
        self._jobs[name] = self.app.after(ms, lambda: (self._jobs.pop(name, None), fn()))

    def _cancel(self, name):
        job = self._jobs.pop(name, None)
        if job:
            try:
                self.app.after_cancel(job)
            except (tk.TclError, ValueError):
                pass

    def _cancel_flashes(self):
        for job in self._flash_jobs:
            try:
                self.app.after_cancel(job)
            except (tk.TclError, ValueError):
                pass
        self._flash_jobs = []

    # ------------------------------------------------------------ state helpers
    def _view(self):
        """(resp, index) currently shown by the main animation, or (None, None)."""
        app = self.app
        if not app.anim_resp or self.reset_flag:
            return app.anim_resp, None
        return app.anim_resp, app.anim_index

    def is_mid_animation(self):
        app = self.app
        if not app.anim_resp:
            return False
        last = len(app.anim_resp["result"]["steps"]) - 1
        return bool(app.anim_playing or app.anim_index < last)

    def is_stale(self):
        app = self.app
        if not app.anim_resp:
            return False
        r = app.anim_resp["result"]
        src, dst = app.get_selection()
        return (r["source"], r["target"], r["algorithm"]) != (src, dst, app.algo_var.get())

    # =================================================================== A2/A3
    def _build_strip(self):
        app = self.app
        self.strip = ctk.CTkFrame(app.map_frame, fg_color=ENH["strip"], corner_radius=8)
        # right padding keeps the strip clear of the floating zoom controls
        self.strip.pack(fill="x", padx=(6, 72), pady=(6, 0), before=app.canvas)
        self.st = {}
        self.mt = {}
        if FEATURES["status_strip"]:
            row = ctk.CTkFrame(self.strip, fg_color="transparent")
            row.pack(fill="x", padx=6, pady=(4, 0))
            for key in ("Algorithm", "Route", "Phase", "Step"):
                self.st[key] = self._chip(row, key)
        if FEATURES["metrics"]:
            row = ctk.CTkFrame(self.strip, fg_color="transparent")
            row.pack(fill="x", padx=6, pady=(2, 4))
            for key in ("Nodes visited", "Edges examined", "Queue size", "Cost so far"):
                self.mt[key] = self._chip(row, key)
        app.map_frame.bind("<Configure>", lambda e: self._after("strip", 60, self.sync_strip), add="+")

    def _chip(self, parent, key):
        cell = ctk.CTkFrame(parent, fg_color=ENH["chip"], corner_radius=6)
        cell.pack(side="left", padx=(0, 6), pady=1)
        k = ctk.CTkLabel(cell, text=key.upper(), font=(FONT, 9, "bold"), text_color=ENH["key"])
        k.pack(side="left", padx=(8, 4))
        v = ctk.CTkLabel(cell, text="—", font=(FONT, 11, "bold"), text_color=ENH["val"])
        v.pack(side="left", padx=(0, 8))
        return k, v

    def _phase(self):
        app = self.app
        resp, i = self._view()
        if self.note:
            return self.note, ENH["drawing"]
        if not resp or i is None:
            return "Idle", ENH["idle"]
        last = len(resp["result"]["steps"]) - 1
        if i < last:
            return ("Exploring" if app.anim_playing else "Exploring · paused"), ENH["exploring"]
        if "drawing" in self._jobs:
            return "Drawing route", ENH["drawing"]
        return "Done", ENH["done"]

    def sync_strip(self):
        app = self.app
        if not hasattr(self, "strip"):
            return
        resp, i = self._view()
        if self.st:
            src, dst = app.get_selection()
            algo = app.algo_var.get()
            if resp:
                src, dst, algo = (resp["result"]["source"], resp["result"]["target"],
                                  resp["result"]["algorithm"])
            wide = app.map_frame.winfo_width() >= 900
            name = (lambda n: n or "—") if wide else (lambda n: short(n) if n else "—")
            self.st["Algorithm"][1].configure(text=algo, text_color=ROUTE_COLORS.get(algo, ENH["val"]))
            self.st["Route"][1].configure(text=f"{name(src)} → {name(dst)}")
            phase, color = self._phase()
            self.st["Phase"][1].configure(text="● " + phase, text_color=color)
            n = len(resp["result"]["steps"]) if resp else None
            self.st["Step"][1].configure(text=f"{i + 1} of {n}" if (n and i is not None)
                                         else (f"0 of {n}" if n else "—"))
        if self.mt:
            algo = resp["result"]["algorithm"] if resp else app.algo_var.get()
            self.mt["Queue size"][0].configure(text=f"{FRONTIER_NAME[algo].upper()} SIZE")
            self.mt["Edges examined"][0].configure(
                text="EDGES RELAXED / EXAMINED" if algo == "Dijkstra" else "EDGES EXAMINED")
            if resp and i is not None:
                m = step_metrics(resp["result"], i, app.nav.graph.adjacency)
                self.mt["Nodes visited"][1].configure(text=str(m["visited"]))
                self.mt["Edges examined"][1].configure(
                    text=f"{m['relaxed']} / {m['examined']}" if algo == "Dijkstra" else str(m["examined"]))
                self.mt["Queue size"][1].configure(text=str(m["frontier"]))
                self.mt["Cost so far"][1].configure(text=fmt_distance(m["cost"]))
            else:
                for key, val in (("Nodes visited", "0"), ("Queue size", "0"), ("Cost so far", "0 m")):
                    self.mt[key][1].configure(text=val)
                self.mt["Edges examined"][1].configure(text="0 / 0" if algo == "Dijkstra" else "0")

    # =================================================================== A1
    def draw_canvas_layers(self, canvas):
        """Called after MapCanvas._draw_overlay – race layer, then label chips."""
        if FEATURES["race"] and self.race:
            self._draw_race(canvas)
        if FEATURES["map_labels"]:
            self._draw_labels(canvas)

    def _draw_labels(self, canvas):
        k = canvas._k()
        size = max(8, min(13, int(round(8 * k))))
        sx, sy = canvas.coord_scale
        for name, (dx, dy) in LABEL_OFFSETS.items():
            if name == canvas.hover_node:          # the hover tooltip already names it
                continue
            x, y = canvas.img_pt(name)
            X, Y = canvas.to_canvas(x + dx * sx, y + dy * sy)
            NX, NY = canvas.node_canvas(name)
            t = canvas.create_text(X, Y, text=name.upper(), fill=COLORS["navy"],
                                   font=(FONT, size, "bold"), tags=("enh_label",))
            x0, y0, x1, y1 = canvas.bbox(t)
            # short leader from the marker edge to the chip edge
            ex = min(max(NX, x0 - 4), x1 + 4)
            ey = min(max(NY, y0 - 2), y1 + 2)
            vx, vy = ex - NX, ey - NY
            d = max(1.0, (vx * vx + vy * vy) ** 0.5)
            r = 10 * k
            if d > r + 2:
                canvas.create_line(NX + vx / d * r, NY + vy / d * r, ex, ey, fill="#0B1F3A",
                                   width=max(1, int(k)), dash=(3, 2), tags=("enh_label",))
            rect = canvas.create_rectangle(x0 - 5, y0 - 2, x1 + 5, y1 + 2, fill="#FFFFFF",
                                           outline=COLORS["navy"], width=1, tags=("enh_label",))
            canvas.tag_raise(t, rect)

    # =================================================================== B1
    def _build_pseudocode(self):
        tab = self.app.tabs.tab("Route")
        self.pc = Collapsible(tab, "PSEUDOCODE", expanded=True)
        self.pc.frame.pack(fill="x", pady=(6, 0))
        self.pc_txt = tk.Text(self.pc.body, height=9, wrap="none", relief="flat", bd=0,
                              highlightthickness=0, bg="#FFFFFF", fg=COLORS["text"],
                              font=(MONO, 9), padx=6, pady=4, cursor="arrow")
        self.pc_txt.tag_configure("num", foreground="#94A3B8")
        self.pc_txt.tag_configure("hl", background=ENH["hl"], foreground=ENH["hl_fg"],
                                  font=(MONO, 9, "bold"))
        self.pc_txt.tag_configure("hl2", background=ENH["hl2"])
        self.pc_txt.pack(fill="x")
        self._pc_algo = None

    def sync_pseudocode(self):
        if not hasattr(self, "pc_txt"):
            return
        app = self.app
        resp, i = self._view()
        algo = resp["result"]["algorithm"] if resp else app.algo_var.get()
        lines = PSEUDOCODE[algo]
        t = self.pc_txt
        t.configure(state="normal")
        if self._pc_algo != algo:
            t.delete("1.0", "end")
            for n, line in enumerate(lines, start=1):
                t.insert("end", f"{n:>2}  ", "num")
                t.insert("end", line + ("\n" if n < len(lines) else ""))
            t.configure(height=len(lines))
            self._pc_algo = algo
            self.pc.set_title(f"PSEUDOCODE – {algo}")
        t.tag_remove("hl", "1.0", "end")
        t.tag_remove("hl2", "1.0", "end")
        if resp and i is not None:
            steps = resp["result"]["steps"]
            done = i == len(steps) - 1 and self._phase()[0] == "Done"
            primary, secondary = pseudo_lines(algo, steps[i], done=done)
            for n in secondary:
                t.tag_add("hl2", f"{n}.0", f"{n}.end+1c")
            if primary:
                t.tag_add("hl", f"{primary}.0", f"{primary}.end+1c")
                t.see(f"{primary}.0")
        t.configure(state="disabled")

    # =================================================================== B2
    def _build_table(self):
        tab = self.app.tabs.tab("Route")
        self.tb = Collapsible(tab, "DISTANCE TABLE", expanded=False)
        self.tb.frame.pack(fill="x", pady=(6, 0))
        grid = tk.Frame(self.tb.body, bg="#FFFFFF")
        grid.pack(fill="x")
        for c, wgt in enumerate((3, 2, 3)):
            grid.grid_columnconfigure(c, weight=wgt)
        self.tb_head = []
        for c in range(3):
            lbl = tk.Label(grid, text="", font=(FONT, 9, "bold"), bg=COLORS["navy"], fg="white",
                           anchor="w", padx=6)
            lbl.grid(row=0, column=c, sticky="nsew")
            self.tb_head.append(lbl)
        self.tb_rows = {}
        for r, node in enumerate(self.app.nav.graph.vertices, start=1):
            cells = []
            for c in range(3):
                lbl = tk.Label(grid, text="", font=(MONO, 9), bg="#FFFFFF", fg=COLORS["text"],
                               anchor="w", padx=6)
                lbl.grid(row=r, column=c, sticky="nsew", pady=(0, 1))
                cells.append(lbl)
            self.tb_rows[node] = cells

    def sync_table(self, flash=False):
        if not hasattr(self, "tb_rows"):
            return
        app = self.app
        resp, i = self._view()
        algo = resp["result"]["algorithm"] if resp else app.algo_var.get()
        dij = algo == "Dijkstra"
        heads = ("Node", "Distance", "Previous") if dij else ("Node", "Visit order", "Parent")
        for lbl, h in zip(self.tb_head, heads):
            lbl.configure(text=h)
        self.tb.set_title("DISTANCE TABLE – Dijkstra" if dij else f"VISIT TABLE – {algo}")
        if not flash:
            self._cancel_flashes()
        steps = resp["result"]["steps"] if resp else None
        idx = 0 if (resp and i is None) else i
        step = steps[idx] if steps else None
        prev = steps[idx - 1] if (steps and idx and idx > 0) else None
        visited = step["visited"] if step else []
        current = step["current"] if (step and i is not None) else None
        for node, (c0, c1, c2) in self.tb_rows.items():
            if step is None:
                a, b = ("∞" if dij else "—"), "—"
            elif dij:
                d = step["distances"].get(node, INF)
                a = "∞" if d == INF else f"{d:g} m"
                p = step["parents"].get(node)
                b = short(p) if p else ("— (source)" if node == resp["result"]["source"] else "—")
            else:
                a = str(visited.index(node) + 1) if node in visited else "—"
                if node in step["parents"]:
                    p = step["parents"][node]
                    b = short(p) if p else "— (source)"
                else:
                    b = "—"
            bg = "#FFFFFF"
            font = (MONO, 9)
            if i is not None and node in visited:
                bg = ENH["final"]
            if node == current:
                bg, font = ENH["current"], (MONO, 9, "bold")
            mark = "▶ " if node == current else ("✓ " if (i is not None and node in visited) else "  ")
            c0.configure(text=f"{mark}{node}", bg=bg, font=font)
            c1.configure(text=a, bg=bg, font=font)
            c2.configure(text=b, bg=bg, font=font)
            if flash and prev is not None:
                changed = []
                if dij:
                    if step["distances"].get(node, INF) != prev["distances"].get(node, INF):
                        changed = [c1, c2]
                else:
                    if node in step["parents"] and node not in prev["parents"]:
                        changed = [c2]
                    if node in visited and node not in prev["visited"]:
                        changed.append(c1)
                for cell in changed:
                    self._flash(cell, bg)

    def _flash(self, cell, restore_bg):
        cell.configure(bg=ENH["flash"])
        job = self.app.after(700, lambda: cell.winfo_exists() and cell.configure(bg=restore_bg))
        self._flash_jobs.append(job)

    # =================================================================== B3
    def _build_adjacency(self):
        tab = self.app.tabs.tab("Graph")
        self.adj = Collapsible(tab, "ADJACENCY LIST  (read from the real graph)", expanded=True)
        self.adj.frame.pack(fill="x", pady=(4, 6))
        self.adj_view = tk.Text(self.adj.body, height=9, wrap="word", relief="flat", bd=0,
                                highlightthickness=0, bg="#FFFFFF", fg=COLORS["text"],
                                font=(FONT, 9), padx=6, pady=4, cursor="arrow")
        self.adj_view.tag_configure("key", font=(FONT, 9, "bold"), foreground=COLORS["navy"])
        self.adj_view.tag_configure("cur", background=ENH["hl"])
        self.adj_view.pack(fill="x")
        self._adj_written = False

    def sync_adjacency(self):
        if not hasattr(self, "adj_view"):
            return
        t = self.adj_view
        t.configure(state="normal")
        g = self.app.nav.graph
        if not self._adj_written:
            t.delete("1.0", "end")
            for n, (u, nbrs) in enumerate(g.adjacency.items()):
                t.insert("end", f"{u}: ", "key")
                t.insert("end", ", ".join(f"{v} ({w:g} m)" for v, w in nbrs.items())
                         + ("\n" if n < len(g.adjacency) - 1 else ""))
            self._adj_written = True
        t.tag_remove("cur", "1.0", "end")
        resp, i = self._view()
        if resp and i is not None:
            cur = resp["result"]["steps"][i]["current"]
            if cur in g.adjacency:
                line = list(g.adjacency).index(cur) + 1
                t.tag_add("cur", f"{line}.0", f"{line}.end")
                t.see(f"{line}.0")
        t.configure(state="disabled")

    # =================================================================== C / E
    def _build_compare_extra(self):
        sf = self.app.cmp_title.master          # the Compare tab's scrollable frame
        self.cx = ctk.CTkFrame(sf, fg_color=ENH["card"], corner_radius=10, border_width=1,
                               border_color=COLORS["border"])
        self.cx.pack(fill="x", pady=(8, 4))
        if FEATURES["why_not"]:
            ctk.CTkLabel(self.cx, text="WHY NOT THE OTHERS?", font=(FONT, 12, "bold"),
                         text_color=COLORS["navy"], anchor="w").pack(fill="x", padx=10, pady=(8, 2))
            self.wn_box = ctk.CTkFrame(self.cx, fg_color="transparent")
            self.wn_box.pack(fill="x", padx=10, pady=(0, 8))
            self._why_not_placeholder()
        if FEATURES["race"]:
            ctk.CTkLabel(self.cx, text="RACE MODE", font=(FONT, 12, "bold"),
                         text_color=COLORS["navy"], anchor="w").pack(fill="x", padx=10, pady=(4, 0))
            ctk.CTkLabel(self.cx, text="All three markers travel their own route at the same speed "
                                       "(metres per tick) – the shortest route arrives first.",
                         font=(FONT, 10), text_color=COLORS["muted"], anchor="w", justify="left",
                         wraplength=320).pack(fill="x", padx=10)
            row = ctk.CTkFrame(self.cx, fg_color="transparent")
            row.pack(fill="x", padx=10, pady=4)
            ctk.CTkButton(row, text="🏁  RACE ALL 3", height=30, width=140, font=(FONT, 12, "bold"),
                          fg_color="#7C3AED", hover_color="#6D28D9",
                          command=self.race_start).pack(side="left")
            ctk.CTkButton(row, text="Stop race", height=30, width=90, fg_color="#475569",
                          hover_color="#334155", command=self.race_stop).pack(side="left", padx=6)
            self.race_board = ctk.CTkFrame(self.cx, fg_color="transparent")
            self.race_board.pack(fill="x", padx=10, pady=(0, 8))

    def _why_not_placeholder(self, text="Select a source and destination, then Run Comparison."):
        for w in self.wn_box.winfo_children():
            w.destroy()
        ctk.CTkLabel(self.wn_box, text=text, font=(FONT, 10), text_color=COLORS["muted"],
                     anchor="w", justify="left", wraplength=320).pack(fill="x")

    def render_why_not(self, resp):
        if not FEATURES["why_not"] or not hasattr(self, "wn_box"):
            return
        if not resp or not resp.get("ok"):
            self._why_not_placeholder((resp or {}).get("error") or
                                      "Select a source and destination, then Run Comparison.")
            return
        for w in self.wn_box.winfo_children():
            w.destroy()
        win, lines = why_not_lines(resp)
        ctk.CTkLabel(self.wn_box, text="🏆 " + win, font=(FONT, 11, "bold"), text_color="#14532D",
                     fg_color="#DCFCE7", corner_radius=6, anchor="w", justify="left",
                     wraplength=320).pack(fill="x", pady=(0, 4), ipady=3, ipadx=4)
        for name, txt in lines:
            ctk.CTkLabel(self.wn_box, text="•  " + txt, font=(FONT, 10),
                         text_color=ui.ALGO_COLORS.get(name, COLORS["text"]), anchor="w",
                         justify="left", wraplength=320).pack(fill="x", pady=1)

    # ------------------------------------------------------------ race (E)
    RACE_ORDER = ("Dijkstra", "BFS", "DFS")          # draw order: thick → thin
    RACE_WIDTH = {"Dijkstra": 10, "BFS": 6, "DFS": 3}
    RACE_LANE = {"Dijkstra": 0, "BFS": -1, "DFS": 1}

    def race_start(self):
        app = self.app
        src, dst = app.get_selection()
        err = app.nav.validate(src, dst)
        if err:
            app.set_status("error", "Race not started", err)
            return
        resp = app.nav.compare(src, dst)
        runners = {}
        for name, key in (("BFS", "bfs"), ("DFS", "dfs"), ("Dijkstra", "dijkstra")):
            r = resp.get(key)
            if r and r["found"]:
                runners[name] = {"res": r, "travelled": 0.0, "finish": None}
        if not runners:
            app.set_status("none", "No Route Available", "No route exists – nothing to race.")
            return
        self.race_stop(render=False)
        longest = max(r["res"]["distance"] for r in runners.values()) or 1
        self.race = {"runners": runners, "tick": 0, "speed": longest / 160.0, "done": False}
        self._race_board_text("Racing…")
        app.set_status("info", "Race in progress",
                       "Cyan = BFS · Magenta = DFS · Green = Dijkstra – equal speed, shortest arrives first.")
        self._race_tick()

    def _race_tick(self):
        race = self.race
        if not race:
            return
        race["tick"] += 1
        for r in race["runners"].values():
            if r["finish"] is None:
                r["travelled"] = min(r["res"]["distance"], r["travelled"] + race["speed"])
                if r["travelled"] >= r["res"]["distance"]:
                    r["finish"] = race["tick"]
        self.app.canvas.render()
        if all(r["finish"] is not None for r in race["runners"].values()):
            race["done"] = True
            self._race_leaderboard()
            return
        self._after("race", 40, self._race_tick)

    def race_stop(self, render=True):
        self._cancel("race")
        had = self.race is not None
        self.race = None
        if hasattr(self, "race_board"):
            for w in self.race_board.winfo_children():
                w.destroy()
        if render and had:
            self.app.canvas.render()

    def _race_board_text(self, text):
        for w in self.race_board.winfo_children():
            w.destroy()
        ctk.CTkLabel(self.race_board, text=text, font=(FONT, 10), text_color=COLORS["muted"],
                     anchor="w").pack(fill="x")

    def _race_leaderboard(self):
        for w in self.race_board.winfo_children():
            w.destroy()
        runners = self.race["runners"]
        order = sorted(runners, key=lambda n: (runners[n]["finish"], runners[n]["res"]["edges"]))
        medals = ["🥇", "🥈", "🥉"]
        ctk.CTkLabel(self.race_board, text="FINISHING LEADERBOARD", font=(FONT, 10, "bold"),
                     text_color=COLORS["navy"], anchor="w").pack(fill="x", pady=(2, 2))
        place, prev = 0, None
        for idx, name in enumerate(order):
            r = runners[name]["res"]
            if runners[name]["finish"] != prev:
                place = idx
            prev = runners[name]["finish"]
            tie = sum(1 for n in order if runners[n]["finish"] == runners[name]["finish"]) > 1
            ctk.CTkLabel(self.race_board,
                         text=f"{medals[place]}  {name:<9} {fmt_distance(r['distance']):>7} · "
                              f"{r['edges']} hops · {len(r['visited'])} visited" + ("  (tie)" if tie else ""),
                         font=(MONO, 10, "bold"), text_color=ROUTE_COLORS[name] if name != "Dijkstra"
                         else "#15803D", fg_color="#0B1F3A" if name != "Dijkstra" else "#DCFCE7",
                         corner_radius=6, anchor="w").pack(fill="x", pady=1, ipadx=4)
        for name in ("BFS", "DFS", "Dijkstra"):
            if name not in runners:
                ctk.CTkLabel(self.race_board, text=f"   {name}: no route", font=(MONO, 10),
                             text_color=COLORS["muted"], anchor="w").pack(fill="x")
        self.app.set_status("found", "Race finished",
                            f"{order[0]} arrives first with {fmt_distance(runners[order[0]]['res']['distance'])}.")

    def _draw_race(self, canvas):
        k = canvas._k()
        for name in self.RACE_ORDER:
            r = self.race["runners"].get(name)
            if not r:
                continue
            pts = canvas.path_points(r["res"]["path"])
            if len(pts) < 2:
                continue
            color = ROUTE_COLORS[name]
            canvas._dashed(pts, 6 * k, 6 * k, fill=color, width=max(1, 1.5 * k))   # planned route
            frac = r["travelled"] / (r["res"]["distance"] or 1)
            part = canvas._partial_polyline(pts, frac)
            if len(part) >= 2:
                canvas.create_line(canvas._flat(part), fill="#0B1F3A",
                                   width=(self.RACE_WIDTH[name] + 3) * k,
                                   capstyle="round", joinstyle="round")
                canvas.create_line(canvas._flat(part), fill=color, width=self.RACE_WIDTH[name] * k,
                                   capstyle="round", joinstyle="round")
        for name in self.RACE_ORDER:
            r = self.race["runners"].get(name)
            if not r:
                continue
            pts = canvas.path_points(r["res"]["path"])
            if len(pts) < 2:
                continue
            x, y, dx, dy = canvas._point_along(pts, r["travelled"] / (r["res"]["distance"] or 1))
            lane = self.RACE_LANE[name] * 7 * k
            x, y = x - dy * lane, y + dx * lane
            mr = 6 * k
            canvas.create_oval(x - mr - 2, y - mr - 2, x + mr + 2, y + mr + 2, fill="#0B1F3A", outline="")
            canvas.create_oval(x - mr, y - mr, x + mr, y + mr, fill=ROUTE_COLORS[name],
                               outline="white", width=2)

    # =================================================================== events
    def on_step(self):
        """A step of the main animation was drawn (show_step)."""
        app = self.app
        self.reset_flag = False
        self.note = None
        resp = app.anim_resp
        if resp:
            last = len(resp["result"]["steps"]) - 1
            if app.anim_index >= last and app.anim_playing:
                self._after("drawing", max(350, int(app._delay() * 0.8)), self.sync)
            else:
                self._cancel("drawing")
        app._set_live_step(app.anim_index if resp else None)
        app._write_graph_steps(resp, app.anim_index)
        self.sync(flash=True)

    def on_reset(self):
        self.reset_flag = True
        self.note = None
        self._cancel("drawing")
        self._cancel_flashes()
        self.race_stop()
        self.app._set_live_step(None)
        self.sync()

    def sync(self, flash=False):
        try:
            self.sync_strip()
            self.sync_pseudocode()
            self.sync_table(flash=flash)
            self.sync_adjacency()
        except tk.TclError:
            pass                     # window is closing


# =============================================================================
# Installation – wrap existing methods (originals always run first)
# =============================================================================
_INSTALLED = False


def _enh(app):
    return app.__dict__.get("enh")


def install_enhancements():
    """Patch ui.CampusNavigationApp / ui.MapCanvas once (before instantiation)."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    App, Canvas = ui.CampusNavigationApp, ui.MapCanvas

    def wrap(cls, name, after=None, before=None):
        orig = getattr(cls, name)

        def wrapper(self, *a, **kw):
            ctx = before(self) if before else None
            result = orig(self, *a, **kw)
            if after:
                after(self, ctx, result)
            return result

        wrapper.__name__ = name
        wrapper.__wrapped__ = orig
        setattr(cls, name, wrapper)

    # ---- construction
    orig_init = App.__init__

    def __init__(self, *a, **kw):
        orig_init(self, *a, **kw)
        self.__dict__["enh"] = Enhancements(self)

    App.__init__ = __init__

    # ---- map layers
    def draw_after(canvas, _ctx, _res):
        e = _enh(canvas.app)
        if e:
            e.draw_canvas_layers(canvas)

    wrap(Canvas, "_draw_overlay", after=draw_after)

    # ---- animation / routing events
    def step_after(self, _ctx, _res):
        e = _enh(self)
        if e:
            e.on_step()

    wrap(App, "show_step", after=step_after)

    def sync_after(self, _ctx, _res):
        e = _enh(self)
        if e:
            e.note = None
            e.sync()

    def find_route_after(self, _ctx, _res):
        e = _enh(self)
        if e:
            e.reset_flag = False
            e.note = None
            e._cancel("drawing")
            self._set_live_step(self.anim_index if self.anim_resp else None)
            self._write_graph_steps(self.anim_resp, self.anim_index)
            e.sync()

    wrap(App, "find_route", after=find_route_after)

    def reset_after(self, _ctx, _res):
        e = _enh(self)
        if e:
            e.on_reset()

    wrap(App, "reset_animation", after=reset_after)

    def clear_after(self, _ctx, _res):
        e = _enh(self)
        if e:
            if FEATURES["robustness"]:
                self._cancel_animation_run()          # also drop partial overlays
            e.on_reset()

    wrap(App, "clear_route", after=clear_after)

    def alt_after(self, _ctx, _res):
        e = _enh(self)
        if e:
            e.reset_flag = True
            e.note = "Alternative route shown" if self.main_paths else None
            e.sync()

    wrap(App, "find_alternative", after=alt_after)

    # toggle_pause: a stale animation (other source / destination / algorithm)
    # is discarded so RESUME never replays an outdated run.
    def pause_before(self):
        e = _enh(self)
        if e and FEATURES["robustness"] and e.is_stale() and not self.anim_playing:
            self._cancel_animation_run()
            self.anim_resp = None
        return None

    wrap(App, "toggle_pause", before=pause_before, after=sync_after)
    wrap(App, "animate_algorithm", after=sync_after)

    # ---- robustness: selection / algorithm change mid-animation
    def _cancel_mid(self, reason):
        self._cancel_animation_run()
        c = self.canvas
        c.routes, c.node_states, c.visit_order, c.tree_edges = [], {}, [], []
        self.main_paths, self.anim_resp = [], None
        c.render()
        self.step_lbl.configure(text=f"{reason} – animation cancelled. Press ANIMATE or NEXT STEP.")
        self.set_status("info", "Animation cancelled", f"{reason} during the animation; overlays were reset.")

    def sel_before(self):
        e = _enh(self)
        mid = bool(e and FEATURES["robustness"] and e.is_mid_animation() and e.is_stale())
        if mid:
            _cancel_mid(self, "Selection changed")
            e.race_stop()
        return mid

    def sel_after(self, mid, _res):
        e = _enh(self)
        if e:
            if mid:
                e.on_reset()
            else:
                e.sync()

    wrap(App, "on_selection_change", before=sel_before, after=sel_after)

    def algo_before(self):
        e = _enh(self)
        return bool(e and FEATURES["robustness"] and e.is_mid_animation())

    def algo_after(self, mid, _res):
        e = _enh(self)
        if mid:
            _cancel_mid(self, "Algorithm changed")
        if e:
            if mid:
                e.on_reset()
            else:
                e.sync()

    wrap(App, "on_algorithm_change", before=algo_before, after=algo_after)

    # ---- compare tab
    def compare_after(self, _ctx, result):
        e = _enh(self)
        if e:
            if result is None:
                src, dst = self.get_selection()
                e.render_why_not(self.nav.compare(src, dst))
            else:
                e.render_why_not(result)

    wrap(App, "update_compare", after=compare_after)
