"""
ui.py
=====
USER INTERFACE + ROUTE VISUALIZER (CustomTkinter + Tkinter Canvas + Pillow).

The UI contains NO algorithm logic. Every calculation is requested from
navigation.NavigationController, which in turn calls algorithms.py.

Components
----------
    MapCanvas            – campus image, zoom / pan, route & node overlays
    VivaWindow           – Explanation window: queue / stack / heap,
                           visited set, parent dictionary, distance table
    CampusNavigationApp  – main dashboard window
"""

import math
import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk
from PIL import Image, ImageTk

from algorithms import COMPLEXITY
from campus_data import (LOCATION_ORDER, MAP_HEIGHT, MAP_WIDTH, NODE_POSITIONS,
                         ROAD_WAYPOINTS, LOCATIONS)
from graph import edge_key
from navigation import NavigationController, path_edges
from utils import (ALGO_COLORS, COLORS, MAP_MISSING_MSG, MAP_PATH, fmt_distance,
                   fmt_edge, fmt_ms, fmt_path_inline, short)

FONT = "Segoe UI"
MONO = "Consolas"
SRC_PLACEHOLDER = "Select starting location"
DST_PLACEHOLDER = "Select destination"

ROUTE_COLORS = {"BFS": "#38BDF8", "DFS": "#D946EF", "Dijkstra": "#00E676"}
ALGO_DESC = {
    "BFS": "Fewest edges · Queue (FIFO)",
    "DFS": "Deep exploration · Stack (LIFO)",
    "Dijkstra": "Shortest distance · Min-heap",
}

# Road polylines derived from the existing overlay (campus_data.ROAD_WAYPOINTS).
# Keyed both (u, v) and (v, u). Graph nodes/edges/weights are not modified.
EDGE_PATHS = {}
for (_u, _v), _mid in ROAD_WAYPOINTS.items():
    EDGE_PATHS[(_u, _v)] = list(_mid)
    EDGE_PATHS[(_v, _u)] = list(reversed(_mid))


# =============================================================================
# Small widget helpers
# =============================================================================
def make_card(master, title=None, **kw):
    frame = ctk.CTkFrame(master, fg_color=COLORS["card"], corner_radius=12,
                         border_width=1, border_color=COLORS["border"], **kw)
    if title:
        ctk.CTkLabel(frame, text=title, font=(FONT, 12, "bold"),
                     text_color=COLORS["muted"], anchor="w").pack(fill="x", padx=14, pady=(10, 2))
    return frame


def make_text(master, height=10, mono=False, bg="#FFFFFF"):
    """Read-only rich text widget (plain tk.Text so that font tags work)."""
    t = tk.Text(master, wrap="word", relief="flat", bd=0, highlightthickness=0,
                bg=bg, fg=COLORS["text"], font=(MONO if mono else FONT, 10),
                padx=12, pady=8, height=height, cursor="arrow", spacing1=1, spacing3=1)
    t.tag_configure("h1", font=(FONT, 13, "bold"), foreground=COLORS["navy"], spacing1=6, spacing3=4)
    t.tag_configure("h2", font=(FONT, 11, "bold"), foreground=COLORS["navy"], spacing1=8, spacing3=2)
    t.tag_configure("label", font=(FONT, 9, "bold"), foreground=COLORS["muted"], spacing1=6)
    t.tag_configure("value", font=(FONT, 11), foreground=COLORS["text"])
    t.tag_configure("big", font=(FONT, 15, "bold"), foreground=COLORS["text"])
    t.tag_configure("route", font=(FONT, 11, "bold"), foreground=COLORS["navy"], lmargin1=10, lmargin2=10)
    t.tag_configure("arrow", font=(FONT, 10), foreground=COLORS["muted"], lmargin1=30)
    t.tag_configure("mono", font=(MONO, 10), foreground=COLORS["text"])
    t.tag_configure("monob", font=(MONO, 10, "bold"), foreground=COLORS["navy"])
    t.tag_configure("muted", font=(FONT, 9), foreground=COLORS["muted"])
    t.tag_configure("green", font=(FONT, 10, "bold"), foreground=COLORS["green"])
    t.tag_configure("red", font=(FONT, 10, "bold"), foreground=COLORS["red"])
    t.tag_configure("orange", font=(FONT, 10, "bold"), foreground="#EA580C")
    t.tag_configure("blue", font=(FONT, 10, "bold"), foreground=COLORS["blue"])
    t.tag_configure("purple", font=(FONT, 10, "bold"), foreground="#7C3AED")
    t.tag_configure("note", font=(FONT, 9, "italic"), foreground="#475569",
                    background="#F1F5F9", lmargin1=6, lmargin2=6, rmargin=6)
    t.configure(state="disabled")
    return t


def write_rich(widget, chunks):
    """chunks = [(text, tag), ...]"""
    widget.configure(state="normal")
    widget.delete("1.0", "end")
    for text, tag in chunks:
        widget.insert("end", text, tag)
    widget.configure(state="disabled")


def with_scrollbar(master, widget_factory):
    holder = ctk.CTkFrame(master, fg_color="transparent")
    widget = widget_factory(holder)
    sb = ctk.CTkScrollbar(holder, command=widget.yview)
    widget.configure(yscrollcommand=sb.set)
    sb.pack(side="right", fill="y")
    widget.pack(side="left", fill="both", expand=True)
    return holder, widget


# =============================================================================
# MAP CANVAS  –  the ROUTE VISUALIZER
# =============================================================================
class MapCanvas(tk.Canvas):
    MIN_ZOOM, MAX_ZOOM = 1.0, 4.0

    def __init__(self, master, app, **kw):
        super().__init__(master, highlightthickness=0, bg="#16243A", **kw)
        self.app = app
        self.image, self.load_error = None, None
        try:
            self.image = Image.open(MAP_PATH).convert("RGB")
        except (FileNotFoundError, OSError):
            self.load_error = MAP_MISSING_MSG
        self.iw, self.ih = self.image.size if self.image else (MAP_WIDTH, MAP_HEIGHT)
        # Node coordinates are defined for a 1024 x 572 image – rescale if the
        # user replaces the picture with a different resolution.
        self.coord_scale = (self.iw / MAP_WIDTH, self.ih / MAP_HEIGHT)

        self.zoom, self.cx, self.cy = 1.0, self.iw / 2, self.ih / 2
        self.s, self.ox, self.oy = 1.0, 0.0, 0.0
        self._photo, self._cache_key, self._cache_fast = None, None, False
        self._render_job = None
        self._press = None
        self._dragging = False

        # ---- overlay state (set by the app) ----
        self.routes = []            # [{"path", "color", "width", "kind"}]
        self.node_states = {}       # node -> "current" | "visited" | "frontier"
        self.visit_order = []       # order numbers shown on visited nodes
        self.tree_edges = []        # search-tree (parent) edges
        self.source = None
        self.target = None
        self.selected = None
        self.hover_node = None
        self.show_network = True
        self.pick_roads = False
        self.anim_active_edge = None   # (u, v) currently travelled
        self.anim_frac = 0.0
        self.anim_trail = []           # list of (u, v) completed trail edges
        self.anim_trail_frac = None    # (u, v, frac) partial trail
        self.pulse_node = None
        self.pulse_name = None
        self.marker_on = False

        self.bind("<Configure>", lambda e: self.schedule_render())
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<MouseWheel>", self._on_wheel)          # Windows / macOS
        self.bind("<Button-4>", lambda e: self._wheel_zoom(e.x, e.y, 1.15))   # Linux
        self.bind("<Button-5>", lambda e: self._wheel_zoom(e.x, e.y, 1 / 1.15))
        self.bind("<Motion>", self._on_motion)
        self.bind("<Leave>", lambda e: self._set_hover(None))

    # ------------------------------------------------------------ geometry
    def _k(self):
        """Overlay size factor – markers grow a little when zooming in."""
        return max(0.8, min(self.s, 2.0))

    def _transform(self):
        W = max(self.winfo_width(), 50)
        H = max(self.winfo_height(), 50)
        fit = min(W / self.iw, H / self.ih)
        s = fit * self.zoom
        half_w, half_h = W / (2 * s), H / (2 * s)
        # keep the map inside the window (no disappearing map)
        self.cx = self.iw / 2 if self.iw <= 2 * half_w else min(max(self.cx, half_w), self.iw - half_w)
        self.cy = self.ih / 2 if self.ih <= 2 * half_h else min(max(self.cy, half_h), self.ih - half_h)
        self.s, self.ox, self.oy = s, W / 2 - self.cx * s, H / 2 - self.cy * s
        return W, H

    def img_pt(self, name):
        x, y = NODE_POSITIONS[name]
        return x * self.coord_scale[0], y * self.coord_scale[1]

    def to_canvas(self, x, y):
        return self.ox + x * self.s, self.oy + y * self.s

    def node_canvas(self, name):
        return self.to_canvas(*self.img_pt(name))

    def edge_img_points(self, u, v):
        """Image-space poly-line for road u -> v (follows the painted road)."""
        mid = EDGE_PATHS.get((u, v), [])
        sx, sy = self.coord_scale
        return [self.img_pt(u)] + [(x * sx, y * sy) for x, y in mid] + [self.img_pt(v)]

    def edge_points(self, u, v):
        """Canvas poly-line for road u -> v (follows the painted road)."""
        return [self.to_canvas(x, y) for x, y in self.edge_img_points(u, v)]

    def path_points(self, path):
        pts = []
        for i in range(len(path) - 1):
            seg = self.edge_points(path[i], path[i + 1])
            pts.extend(seg if not pts else seg[1:])
        return pts

    @staticmethod
    def _flat(pts):
        return [c for p in pts for c in p]

    @staticmethod
    def _point_along(pts, frac):
        """Point at fraction `frac` of the poly-line length + unit direction."""
        lengths = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:])]
        total = sum(lengths) or 1
        target, acc = total * max(0.0, min(1.0, frac)), 0
        for (a, b), L in zip(zip(pts, pts[1:]), lengths):
            if acc + L >= target and L > 0:
                t = (target - acc) / L
                return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t,
                        (b[0] - a[0]) / L, (b[1] - a[1]) / L)
            acc += L
        return pts[-1][0], pts[-1][1], 1, 0

    @staticmethod
    def _partial_polyline(pts, frac):
        """Prefix of a poly-line covering fraction `frac` of its length."""
        if not pts:
            return []
        frac = max(0.0, min(1.0, frac))
        if frac <= 0:
            return [pts[0]]
        lengths = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:])]
        total = sum(lengths) or 1
        target, acc, out = total * frac, 0.0, [pts[0]]
        for (a, b), L in zip(zip(pts, pts[1:]), lengths):
            if acc + L >= target:
                if L > 0:
                    t = (target - acc) / L
                    out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
                else:
                    out.append(b)
                return out
            out.append(b)
            acc += L
        return pts

    @staticmethod
    def _ease(t):
        t = max(0.0, min(1.0, t))
        return t * t * (3 - 2 * t)

    def clear_anim_overlay(self):
        self.anim_active_edge = None
        self.anim_frac = 0.0
        self.anim_trail = []
        self.anim_trail_frac = None
        self.pulse_node = None
        self.pulse_name = None
        self.marker_on = False

    # ------------------------------------------------------------ rendering
    def schedule_render(self, delay=25):
        if self._render_job:
            self.after_cancel(self._render_job)
        self._render_job = self.after(delay, self.render)

    def render(self, fast=False):
        self._render_job = None
        self.delete("all")
        W, H = self._transform()
        s, ox, oy = self.s, self.ox, self.oy

        if self.image is None:
            self.create_rectangle(ox, oy, ox + self.iw * s, oy + self.ih * s,
                                  fill="#1F3354", outline="#3B5378", width=2)
        else:
            bx0, by0 = max(0, int(math.floor(-ox / s))), max(0, int(math.floor(-oy / s)))
            bx1 = min(self.iw, int(math.ceil((W - ox) / s)))
            by1 = min(self.ih, int(math.ceil((H - oy) / s)))
            dw, dh = max(1, int(round((bx1 - bx0) * s))), max(1, int(round((by1 - by0) * s)))
            key = (bx0, by0, bx1, by1, dw, dh)
            if key != self._cache_key or (self._cache_fast and not fast):
                resample = Image.BILINEAR if fast else Image.LANCZOS
                img = self.image.crop((bx0, by0, bx1, by1)).resize((dw, dh), resample)
                self._photo = ImageTk.PhotoImage(img)
                self._cache_key, self._cache_fast = key, fast
            self.create_image(ox + bx0 * s, oy + by0 * s, image=self._photo, anchor="nw")

        self._draw_overlay()

        if self.load_error:
            self.create_rectangle(W / 2 - 300, 20, W / 2 + 300, 70, fill="#7F1D1D", outline="#FCA5A5")
            self.create_text(W / 2, 45, text="⚠  " + self.load_error, fill="white",
                             font=(FONT, 11, "bold"), width=580)

    def _draw_overlay(self):
        k = self._k()
        graph = self.app.nav.graph

        # 1. road network (thin) + distance badges – always visible
        for u, v, w in graph.edges():
            pts = self.edge_points(u, v)
            self.create_line(self._flat(pts), fill="#0B1F3A", width=4 * k,
                             capstyle="round", joinstyle="round")
            self.create_line(self._flat(pts), fill="#BAE6FD", width=1.6 * k,
                             capstyle="round", joinstyle="round")

        # 2. search tree edges (animation / explanation)
        for (p, c) in self.tree_edges:
            pts = self.edge_points(p, c)
            self.create_line(self._flat(pts), fill="#1D4ED8", width=4 * k,
                             capstyle="round", joinstyle="round")
            self.create_line(self._flat(pts), fill="#93C5FD", width=2 * k,
                             capstyle="round", joinstyle="round")

        # 3. completed green trail (phase B) + glow on the active edge
        if self.anim_trail:
            tpts = []
            for (u, v) in self.anim_trail:
                seg = self.edge_points(u, v)
                tpts.extend(seg if not tpts else seg[1:])
            if tpts:
                self.create_line(self._flat(tpts), fill="#064E3B", width=10 * k,
                                 capstyle="round", joinstyle="round")
                self.create_line(self._flat(tpts), fill="#00E676", width=6 * k,
                                 capstyle="round", joinstyle="round")
        if self.anim_trail_frac:
            u, v, frac = self.anim_trail_frac
            pts = self.edge_points(u, v)
            part = self._partial_polyline(pts, frac)
            if len(part) >= 2:
                self.create_line(self._flat(part), fill="#00E676", width=6 * k,
                                 capstyle="round", joinstyle="round")
        if self.anim_active_edge:
            u, v = self.anim_active_edge
            pts = self.edge_points(u, v)
            flat = self._flat(pts)
            self.create_line(flat, fill="#FDE68A", width=10 * k,
                             capstyle="round", joinstyle="round")
            self.create_line(flat, fill="#FACC15", width=4.5 * k,
                             capstyle="round", joinstyle="round")
            part = self._partial_polyline(pts, self.anim_frac)
            if len(part) >= 2:
                self.create_line(self._flat(part), fill="#F59E0B", width=5 * k,
                                 capstyle="round", joinstyle="round")

        # 4. routes (dim first, then highlighted)
        for r in sorted(self.routes, key=lambda r: 0 if r.get("kind") == "dim" else 1):
            self._draw_route(r)

        # 5. distance badges on top of lines
        for u, v, w in graph.edges():
            x, y, _, _ = self._point_along(self.edge_points(u, v), 0.5)
            self._badge(x, y, f"{w} m", COLORS["navy"], size=max(7, int(7.5 * k)))

        # 6. nodes
        order = {n: i + 1 for i, n in enumerate(self.visit_order)}
        for name in NODE_POSITIONS:
            X, Y = self.node_canvas(name)
            state = self.node_states.get(name)
            r = 8 * k
            if name == self.pulse_node:
                pr = r + 10 * k
                self.create_oval(X - pr, Y - pr, X + pr, Y + pr, outline="#FACC15", width=3)
            if name == self.selected or name == self.hover_node:
                self.create_oval(X - r - 7 * k, Y - r - 7 * k, X + r + 7 * k, Y + r + 7 * k,
                                 outline="#FFFFFF", width=2)
            if state == "current":
                self.create_oval(X - r - 6 * k, Y - r - 6 * k, X + r + 6 * k, Y + r + 6 * k,
                                 outline="#FACC15", width=3)
                self.create_oval(X - r - 2, Y - r - 2, X + r + 2, Y + r + 2,
                                 fill="#FACC15", outline="#713F12", width=2)
            elif state == "visited":
                self.create_oval(X - r, Y - r, X + r, Y + r, fill="#3B82F6",
                                 outline="#FFFFFF", width=2)
            elif state == "frontier":
                self.create_oval(X - r, Y - r, X + r, Y + r, fill="#F5F3FF",
                                 outline="#A855F7", width=3)
            else:   # normal – subtle semi-transparent marker
                self.create_oval(X - r, Y - r, X + r, Y + r, fill="#FFFFFF",
                                 stipple="gray50", outline="#0B1F3A", width=2)
                self.create_oval(X - 2.5 * k, Y - 2.5 * k, X + 2.5 * k, Y + 2.5 * k,
                                 fill="#0B1F3A", outline="")
            if name in order:
                bx, by = X + r + 2 * k, Y - r - 2 * k
                self.create_oval(bx - 7 * k, by - 7 * k, bx + 7 * k, by + 7 * k,
                                 fill="#1E3A8A", outline="white", width=1)
                self.create_text(bx, by, text=str(order[name]), fill="white",
                                 font=(FONT, max(6, int(7 * k)), "bold"))

        # 7. start / destination pins (distinct green / red)
        if self.source:
            self._pin(*self.node_canvas(self.source), COLORS["green"], "S")
        if self.target:
            self._pin(*self.node_canvas(self.target), COLORS["red"], "D")
        if self.pulse_name and self.pulse_node:
            X, Y = self.node_canvas(self.pulse_node)
            self._badge(X, Y - 36 * k, self.pulse_name, "#14532D",
                        size=max(8, int(9 * k)))

        # travelling marker
        if self.marker_on and self.anim_active_edge:
            u, v = self.anim_active_edge
            x, y, dx, dy = self._point_along(self.edge_points(u, v), self.anim_frac)
            mr = 7 * k
            self.create_oval(x - mr - 3, y - mr - 3, x + mr + 3, y + mr + 3,
                             outline="#FFFFFF", width=2)
            self.create_oval(x - mr, y - mr, x + mr, y + mr,
                             fill="#16A34A", outline="#064E3B", width=2)

        # 8. hover tooltip
        if self.hover_node:
            X, Y = self.node_canvas(self.hover_node)
            deg = len(self.app.nav.graph.adjacency[self.hover_node])
            self._badge(X, Y + 24 * k, f"{self.hover_node}  ·  {deg} roads", "#0F172A",
                        size=max(8, int(8.5 * k)))

    def _draw_route(self, r):
        k = self._k()
        path = r["path"]
        if not path or len(path) < 2:
            return
        pts = self.path_points(path)
        flat = self._flat(pts)
        width = r.get("width", 8) * k
        if r.get("kind") == "dim":
            self.create_line(flat, fill="#1E293B", width=width + 2, capstyle="round", joinstyle="round")
            self._dashed(pts, 10 * k, 7 * k, fill=r["color"], width=width - 1)
            return
        if r.get("kind") == "alt":
            self.create_line(flat, fill="#7C2D12", width=width + 3 * k,
                             capstyle="round", joinstyle="round")
            self.create_line(flat, fill=r["color"], width=width, capstyle="round", joinstyle="round")
            return
        self.create_line(flat, fill="#0B1F3A", width=width + 5 * k, capstyle="round", joinstyle="round")
        self.create_line(flat, fill=r["color"], width=width, capstyle="round", joinstyle="round")
        # direction arrows every ~70 px along the route
        lengths = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:])]
        total = sum(lengths)
        n = max(1, int(total // (70 * k)))
        for i in range(n):
            x, y, dx, dy = self._point_along(pts, (i + 0.5) / n)
            nx, ny = -dy, dx
            a = 6 * k
            self.create_polygon(x + dx * a * 1.3, y + dy * a * 1.3,
                                x - dx * a + nx * a, y - dy * a + ny * a,
                                x - dx * a * 0.4, y - dy * a * 0.4,
                                x - dx * a - nx * a, y - dy * a - ny * a,
                                fill="#0B1F3A", outline="")

    def _dashed(self, pts, dash, gap, **kw):
        """Manual dashed poly-line (renders identically on every platform)."""
        on, remaining = True, dash
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            seg = math.hypot(x1 - x0, y1 - y0)
            if seg == 0:
                continue
            ux, uy = (x1 - x0) / seg, (y1 - y0) / seg
            pos = 0.0
            while pos < seg:
                step = min(remaining, seg - pos)
                if on:
                    self.create_line(x0 + ux * pos, y0 + uy * pos,
                                     x0 + ux * (pos + step), y0 + uy * (pos + step),
                                     capstyle="butt", **kw)
                pos += step
                remaining -= step
                if remaining <= 1e-6:
                    on = not on
                    remaining = dash if on else gap

    def _badge(self, x, y, text, bg, size=8, fg="white"):
        t = self.create_text(x, y, text=text, fill=fg, font=(FONT, size, "bold"))
        x0, y0, x1, y1 = self.bbox(t)
        rect = self.create_rectangle(x0 - 5, y0 - 1, x1 + 5, y1 + 1, fill=bg, outline="white", width=1)
        self.tag_raise(t, rect)

    def _pin(self, X, Y, color, letter):
        k = self._k()
        r, h = 11 * k, 30 * k
        cy = Y - h
        self.create_oval(X - 6 * k, Y - 2.5 * k, X + 6 * k, Y + 2.5 * k, fill="#000000",
                         stipple="gray50", outline="")
        self.create_polygon(X - r * 0.8, cy + r * 0.45, X + r * 0.8, cy + r * 0.45, X, Y,
                            fill=color, outline="white", width=1)
        self.create_oval(X - r, cy - r, X + r, cy + r, fill=color, outline="white", width=2)
        self.create_text(X, cy, text=letter, fill="white", font=(FONT, max(7, int(9 * k)), "bold"))

    # ------------------------------------------------------------ hit tests
    def node_at(self, X, Y):
        best, best_d = None, max(16, 20 * self._k())
        for name in NODE_POSITIONS:
            nx, ny = self.node_canvas(name)
            d = math.hypot(nx - X, ny - Y)
            if self.source == name or self.target == name:     # pins are clickable too
                d = min(d, math.hypot(nx - X, ny - 30 * self._k() - Y))
            if d < best_d:
                best, best_d = name, d
        return best

    def edge_at(self, X, Y, tol=10):
        best, best_d = None, tol
        for u, v, _ in self.app.nav.graph.edges():
            pts = self.edge_points(u, v)
            for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
                dx, dy = x1 - x0, y1 - y0
                L2 = dx * dx + dy * dy
                t = 0 if L2 == 0 else max(0, min(1, ((X - x0) * dx + (Y - y0) * dy) / L2))
                d = math.hypot(X - (x0 + t * dx), Y - (y0 + t * dy))
                if d < best_d:
                    best, best_d = (u, v), d
        return best

    # ------------------------------------------------------------ events
    def _on_press(self, e):
        self._press = (e.x, e.y, self.cx, self.cy)
        self._dragging = False

    def _on_drag(self, e):
        if not self._press:
            return
        x0, y0, cx0, cy0 = self._press
        if not self._dragging and math.hypot(e.x - x0, e.y - y0) > 5:
            self._dragging = True
            self.configure(cursor="fleur")
        if self._dragging and self.zoom > 1.0:
            self.cx = cx0 - (e.x - x0) / self.s
            self.cy = cy0 - (e.y - y0) / self.s
            self.render(fast=True)

    def _on_release(self, e):
        if self._dragging:
            self._dragging = False
            self.configure(cursor="")
            self.render()
            return
        node = self.node_at(e.x, e.y)
        if node:
            self.app.on_node_click(node)

    def _on_wheel(self, e):
        self._wheel_zoom(e.x, e.y, 1.15 if e.delta > 0 else 1 / 1.15)

    def _wheel_zoom(self, X, Y, factor):
        ix, iy = (X - self.ox) / self.s, (Y - self.oy) / self.s
        new_zoom = min(self.MAX_ZOOM, max(self.MIN_ZOOM, self.zoom * factor))
        if new_zoom == self.zoom:
            return
        self.zoom = new_zoom
        W, H = max(self.winfo_width(), 50), max(self.winfo_height(), 50)
        s = min(W / self.iw, H / self.ih) * self.zoom
        self.cx, self.cy = ix - (X - W / 2) / s, iy - (Y - H / 2) / s
        self.render(fast=True)
        self.schedule_render(150)
        self.app.update_zoom_label()

    def _on_motion(self, e):
        node = self.node_at(e.x, e.y)
        if node:
            self.configure(cursor="hand2")
        else:
            self.configure(cursor="")
        self._set_hover(node)

    def _set_hover(self, node):
        if node != self.hover_node:
            self.hover_node = node
            self.render()

    # ------------------------------------------------------------ zoom API
    def zoom_by(self, factor):
        self.zoom = min(self.MAX_ZOOM, max(self.MIN_ZOOM, self.zoom * factor))
        self.render()

    def reset_view(self):
        self.zoom, self.cx, self.cy = 1.0, self.iw / 2, self.ih / 2
        self.render()


# =============================================================================
# EXPLANATION WINDOW
# =============================================================================
class VivaWindow(ctk.CTkToplevel):
    """Shows the internal data structures of the algorithm step by step."""

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("Explanation – Algorithm Internals")
        self.geometry("1180x760")
        self.minsize(980, 620)
        self.configure(fg_color=COLORS["bg"])
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.after(200, self.lift)

        # ---------- header ----------
        head = ctk.CTkFrame(self, fg_color=COLORS["navy"], corner_radius=0, height=58)
        head.pack(fill="x")
        ctk.CTkLabel(head, text="EXPLANATION", font=(FONT, 18, "bold"),
                     text_color="white").pack(side="left", padx=18, pady=12)
        self.head_info = ctk.CTkLabel(head, text="", font=(FONT, 12), text_color="#BFDBFE")
        self.head_info.pack(side="left", padx=10)
        ctk.CTkButton(head, text="↻ Load current selection", width=190, fg_color="#1E40AF",
                      hover_color="#1D4ED8", command=self.app.prepare_viva).pack(side="right", padx=14)

        # ---------- controls ----------
        ctrl = ctk.CTkFrame(self, fg_color="transparent")
        ctrl.pack(fill="x", padx=14, pady=(10, 4))
        btn = dict(width=96, height=32, fg_color=COLORS["navy_2"], hover_color="#1E3A8A")
        ctk.CTkButton(ctrl, text="⏮ First", command=lambda: self.app.goto_step(0), **btn).pack(side="left", padx=3)
        ctk.CTkButton(ctrl, text="◀ Prev", command=lambda: self.app.goto_step(self.app.anim_index - 1),
                      **btn).pack(side="left", padx=3)
        self.play_btn = ctk.CTkButton(ctrl, text="▶ Play", command=self.app.toggle_pause,
                                      width=96, height=32, fg_color=COLORS["green"], hover_color="#15803D")
        self.play_btn.pack(side="left", padx=3)
        ctk.CTkButton(ctrl, text="Next ▶", command=lambda: self.app.goto_step(self.app.anim_index + 1),
                      **btn).pack(side="left", padx=3)
        ctk.CTkButton(ctrl, text="Last ⏭", command=lambda: self.app.goto_step(10 ** 6), **btn).pack(side="left", padx=3)
        self.step_lbl = ctk.CTkLabel(ctrl, text="", font=(FONT, 13, "bold"), text_color=COLORS["navy"])
        self.step_lbl.pack(side="left", padx=16)

        self.action_lbl = ctk.CTkLabel(self, text="", font=(FONT, 13), text_color="#7C2D12",
                                       fg_color="#FFEDD5", corner_radius=8, anchor="w",
                                       justify="left", wraplength=1100)
        self.action_lbl.pack(fill="x", padx=16, pady=(4, 8), ipady=6, ipadx=8)

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        body.grid_columnconfigure(0, weight=2)
        body.grid_columnconfigure(1, weight=3)
        body.grid_rowconfigure(0, weight=1)

        # left: current graph
        left = make_card(body, "CURRENT GRAPH  (adjacency list)")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        holder, self.graph_txt = with_scrollbar(left, lambda m: make_text(m, mono=True))
        holder.pack(fill="both", expand=True, padx=8, pady=(0, 10))

        # right: data structures
        right = ctk.CTkFrame(body, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew")
        self.ds_card = make_card(right, "DATA STRUCTURE")
        self.ds_card.pack(fill="x", pady=(0, 8))
        self.ds_title = ctk.CTkLabel(self.ds_card, text="", font=(FONT, 11), text_color=COLORS["muted"])
        self.ds_title.pack(anchor="w", padx=14)
        self.ds_row = ctk.CTkFrame(self.ds_card, fg_color="transparent", height=44)
        self.ds_row.pack(fill="x", padx=12, pady=(4, 12))

        vis_card = make_card(right, "VISITED  (processing order)")
        vis_card.pack(fill="x", pady=(0, 8))
        self.vis_row = ctk.CTkFrame(vis_card, fg_color="transparent", height=40)
        self.vis_row.pack(fill="x", padx=12, pady=(4, 12))

        tab_card = make_card(right, "PARENT DICTIONARY  &  DISTANCE / LEVEL TABLE")
        tab_card.pack(fill="both", expand=True, pady=(0, 8))
        holder2, self.table_txt = with_scrollbar(tab_card, lambda m: make_text(m, mono=True, height=10))
        holder2.pack(fill="both", expand=True, padx=8, pady=(0, 10))

        route_card = make_card(right, "FINAL ROUTE")
        route_card.pack(fill="x")
        self.route_lbl = ctk.CTkLabel(route_card, text="—", font=(FONT, 13, "bold"),
                                      text_color=COLORS["navy"], wraplength=640, justify="left")
        self.route_lbl.pack(anchor="w", padx=14, pady=(0, 12))

    def _close(self):
        self.app.viva = None
        self.destroy()

    def _chips(self, frame, items, color, empty="(empty)"):
        for w in frame.winfo_children():
            w.destroy()
        if not items:
            ctk.CTkLabel(frame, text=empty, text_color=COLORS["muted"], font=(FONT, 11)).pack(side="left")
            return
        for i, text in enumerate(items):
            ctk.CTkLabel(frame, text=f" {text} ", fg_color=color, text_color="white",
                         corner_radius=6, font=(FONT, 11, "bold")).pack(side="left", padx=2, pady=2)

    def show_graph(self):
        g = self.app.nav.graph
        chunks = [("Vertices (V) = %d    Edges (E) = %d\n" % (g.num_vertices(), g.num_edges()), "monob"),
                  ("Weighted · Undirected · Adjacency List\n\n", "muted")]
        for u, nbrs in g.adjacency.items():
            chunks.append((f"{u} [{short(u)}]\n", "monob"))
            for v, w in nbrs.items():
                tag = "red" if g.is_blocked(u, v) else "mono"
                suffix = "   ⛔ BLOCKED" if g.is_blocked(u, v) else ""
                chunks.append((f"    → {v:<24}{w:>4} m{suffix}\n", tag))
        write_rich(self.graph_txt, chunks)

    def update_view(self, resp, index, playing):
        self.show_graph()
        self.play_btn.configure(text="⏸ Pause" if playing else "▶ Play")
        if not resp:
            self.head_info.configure(text="Select source, destination and algorithm in the main window, "
                                          "then press 'Load current selection'.")
            return
        res = resp["result"]
        algo = res["algorithm"]
        steps = res["steps"]
        index = max(0, min(index, len(steps) - 1))
        step = steps[index]
        self.head_info.configure(text=f"Source: {res['source']}   →   Destination: {res['target']}"
                                      f"     |     Algorithm: {algo}")
        self.step_lbl.configure(text=f"Step {index + 1} / {len(steps)}")
        self.action_lbl.configure(text="  " + step["action"])

        if algo == "BFS":
            self.ds_title.configure(text="QUEUE (FIFO)   front → back")
            items = [short(v) for v in step["frontier"]]
            color = "#2563EB"
        elif algo == "DFS":
            self.ds_title.configure(text="STACK (LIFO)   bottom → top")
            items = [short(v) for v in step["frontier"]]
            color = "#7C3AED"
        else:
            self.ds_title.configure(text="PRIORITY QUEUE (binary min-heap)   (distance, vertex) – minimum on the left")
            items = [f"({d}, {short(v)})" for d, v in step["frontier"]]
            color = "#16A34A"
        self._chips(self.ds_row, items, color)
        self._chips(self.vis_row, [f"{i + 1}. {short(v)}" for i, v in enumerate(step["visited"])], "#1E3A8A")

        # parent / distance table
        col3 = {"BFS": "Level", "DFS": "Depth", "Dijkstra": "Distance"}[algo]
        lines = [(f"{'Vertex':<26}{'Parent':<26}{col3:>9}   Status\n", "monob"),
                 ("─" * 74 + "\n", "muted")]
        visited = set(step["visited"])
        frontier_names = ({v for _, v in step["frontier"]} if algo == "Dijkstra"
                          else set(step["frontier"]))
        for v in self.app.nav.graph.vertices:
            parent = step["parents"].get(v, "—") if v in step["parents"] else "—"
            parent = "None (source)" if parent is None else parent
            d = step["distances"].get(v, float("inf"))
            dtxt = "∞" if d == float("inf") else (f"{d} m" if algo == "Dijkstra" else str(d))
            if v == step["current"]:
                status, tag = "CURRENT", "orange"
            elif v in visited:
                status, tag = ("finalised" if algo == "Dijkstra" else "visited"), "blue"
            elif v in frontier_names:
                status, tag = "in " + {"BFS": "queue", "DFS": "stack", "Dijkstra": "heap"}[algo], "purple"
            else:
                status, tag = "unvisited", "mono"
            lines.append((f"{v:<26}{parent:<26}{dtxt:>9}   ", "mono"))
            lines.append((status + "\n", tag))
        write_rich(self.table_txt, lines)

        if index == len(steps) - 1:
            if res["found"]:
                self.route_lbl.configure(
                    text=f"{fmt_path_inline(res['path'])}\n{res['edges']} edges · "
                         f"{fmt_distance(res['distance'])} · {len(res['visited'])} nodes visited",
                    text_color=COLORS["green"])
            else:
                self.route_lbl.configure(text="No route found.", text_color=COLORS["red"])
        else:
            self.route_lbl.configure(text="(computed when the algorithm finishes)",
                                     text_color=COLORS["muted"])


# =============================================================================
# MAIN APPLICATION WINDOW
# =============================================================================
class CampusNavigationApp(ctk.CTk):
    def __init__(self):
        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme("blue")
        super().__init__()
        self.title("Intelligent Campus Navigation System – Graph-Based Smart Route Planner")
        self.geometry("1600x920")
        self.minsize(1200, 720)
        self.configure(fg_color=COLORS["bg"])

        self.nav = NavigationController()
        self.current_resp = None      # last route / alternative response
        self.current_kind = None      # "route" | "alternative" | "compare"
        self.main_paths = []          # paths currently highlighted
        # animation state
        self.anim_resp = None
        self.anim_index = 0
        self.anim_playing = False
        self.anim_job = None
        self.anim_gen = 0
        self.anim_phase = "A"
        self.anim_event_i = 0
        self.anim_step_target = None
        self.viva = None

        self._build_header()
        self._build_body()
        self._build_statusbar()
        self.after(100, self._initial_render)

    # ================================================================ layout
    def _build_header(self):
        head = ctk.CTkFrame(self, fg_color=COLORS["navy"], corner_radius=0, height=70)
        head.pack(fill="x")
        head.pack_propagate(False)
        logo = ctk.CTkLabel(head, text="◆", font=(FONT, 30, "bold"), text_color="#38BDF8")
        logo.pack(side="left", padx=(20, 8))
        titles = ctk.CTkFrame(head, fg_color="transparent")
        titles.pack(side="left", pady=8)
        ctk.CTkLabel(titles, text="INTELLIGENT CAMPUS NAVIGATION SYSTEM", font=(FONT, 21, "bold"),
                     text_color="white").pack(anchor="w")
        ctk.CTkLabel(titles, text="Graph-Based Smart Route Planner   ·   BFS  ·  DFS  ·  Dijkstra",
                     font=(FONT, 12), text_color="#93C5FD").pack(anchor="w")
        ctk.CTkButton(head, text="🎓  EXPLANATION", width=140, height=36, font=(FONT, 13, "bold"),
                      fg_color="#F59E0B", hover_color="#D97706", text_color="#0B1F3A",
                      command=self.open_viva).pack(side="right", padx=(8, 20))
        ctk.CTkButton(head, text="How It Works", width=120, height=36, font=(FONT, 12),
                      fg_color="#1E3A8A", hover_color="#1D4ED8",
                      command=lambda: self.tabs.set("Learn")).pack(side="right", padx=4)
        ctk.CTkButton(head, text="Algorithm Comparison", width=170, height=36, font=(FONT, 12),
                      fg_color="#1E3A8A", hover_color="#1D4ED8",
                      command=self.open_comparison).pack(side="right", padx=4)

    def _build_body(self):
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=10, pady=(10, 0))
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)
        self._build_left(body)
        self._build_map(body)
        self._build_right(body)

    # ---------------------------------------------------------------- left
    def _build_left(self, parent):
        left = ctk.CTkScrollableFrame(parent, width=280, fg_color="transparent",
                                      scrollbar_button_color="#CBD5E1")
        left.grid(row=0, column=0, sticky="ns", padx=(0, 10))

        # ---- navigation card
        nav = make_card(left, "NAVIGATION")
        nav.pack(fill="x", pady=(0, 10))
        lbl = dict(font=(FONT, 11, "bold"), text_color=COLORS["text"], anchor="w")
        om = dict(width=250, height=34, dynamic_resizing=False, font=(FONT, 12),
                  fg_color="#F1F5F9", button_color="#CBD5E1", button_hover_color="#94A3B8",
                  text_color=COLORS["text"], dropdown_font=(FONT, 12))

        ctk.CTkLabel(nav, text="🟢  SOURCE LOCATION", **lbl).pack(fill="x", padx=14, pady=(4, 2))
        self.src_var = tk.StringVar(value=SRC_PLACEHOLDER)
        ctk.CTkOptionMenu(nav, variable=self.src_var, values=LOCATION_ORDER,
                          command=lambda _: self.on_selection_change(), **om).pack(padx=14)
        ctk.CTkButton(nav, text="⇅  swap", width=70, height=22, font=(FONT, 10),
                      fg_color="transparent", text_color=COLORS["accent"], hover_color="#E0E7FF",
                      command=self.swap_locations).pack(anchor="e", padx=14, pady=(2, 0))
        ctk.CTkLabel(nav, text="🔴  DESTINATION", **lbl).pack(fill="x", padx=14, pady=(0, 2))
        self.dst_var = tk.StringVar(value=DST_PLACEHOLDER)
        ctk.CTkOptionMenu(nav, variable=self.dst_var, values=LOCATION_ORDER,
                          command=lambda _: self.on_selection_change(), **om).pack(padx=14)

        ctk.CTkLabel(nav, text="ALGORITHM", **lbl).pack(fill="x", padx=14, pady=(12, 2))
        self.algo_var = tk.StringVar(value="Dijkstra")
        for name in ("BFS", "DFS", "Dijkstra"):
            row = ctk.CTkFrame(nav, fg_color="transparent")
            row.pack(fill="x", padx=14, pady=1)
            ctk.CTkRadioButton(row, text=name, variable=self.algo_var, value=name, width=90,
                               font=(FONT, 12, "bold"), fg_color=ALGO_COLORS[name],
                               command=self.on_algorithm_change).pack(side="left")
            ctk.CTkLabel(row, text=ALGO_DESC[name], font=(FONT, 10),
                         text_color=COLORS["muted"]).pack(side="left")

        b = dict(height=40, corner_radius=10, font=(FONT, 13, "bold"))
        ctk.CTkButton(nav, text="➤  FIND ROUTE", fg_color=COLORS["accent"], hover_color="#1D4ED8",
                      command=self.find_route, **b).pack(fill="x", padx=14, pady=(14, 6))
        ctk.CTkButton(nav, text="⤳  FIND ALTERNATIVE", fg_color=COLORS["orange"], hover_color="#EA580C",
                      command=self.find_alternative, **b).pack(fill="x", padx=14, pady=(0, 6))
        ctk.CTkButton(nav, text="✕  CLEAR ROUTE", fg_color="#E2E8F0", hover_color="#CBD5E1",
                      text_color=COLORS["text"], command=self.clear_route,
                      **b).pack(fill="x", padx=14, pady=(0, 14))

        # ---- animation card
        an = make_card(left, "ALGORITHM ANIMATION")
        an.pack(fill="x", pady=(0, 10))
        ctk.CTkButton(an, text="▶  ANIMATE ALGORITHM", height=36, corner_radius=10,
                      font=(FONT, 12, "bold"), fg_color="#7C3AED", hover_color="#6D28D9",
                      command=self.animate_algorithm).pack(fill="x", padx=14, pady=(4, 6))
        row = ctk.CTkFrame(an, fg_color="transparent")
        row.pack(fill="x", padx=14)
        self.pause_btn = ctk.CTkButton(row, text="⏸ PAUSE", height=30, width=118, fg_color="#475569",
                                       hover_color="#334155", command=self.toggle_pause)
        self.pause_btn.pack(side="left", expand=True, fill="x", padx=(0, 3))
        ctk.CTkButton(row, text="⟲ RESET", height=30, width=118, fg_color="#475569",
                      hover_color="#334155", command=self.reset_animation).pack(side="left", expand=True,
                                                                                 fill="x", padx=(3, 0))
        self.next_btn = ctk.CTkButton(an, text="⏭ NEXT STEP", height=30, fg_color="#475569",
                                      hover_color="#334155", command=self.next_step)
        self.next_btn.pack(fill="x", padx=14, pady=(6, 0))
        srow = ctk.CTkFrame(an, fg_color="transparent")
        srow.pack(fill="x", padx=14, pady=(8, 0))
        ctk.CTkLabel(srow, text="Speed", font=(FONT, 10), text_color=COLORS["muted"]).pack(side="left")
        self.speed = ctk.CTkSlider(srow, from_=0, to=100, number_of_steps=20, width=180)
        self.speed.set(55)
        self.speed.pack(side="left", padx=8)
        self.step_lbl = ctk.CTkLabel(an, text="Watch the algorithm explore the campus step by step.",
                                     font=(FONT, 10), text_color=COLORS["muted"], wraplength=245,
                                     justify="left", anchor="w")
        self.step_lbl.pack(fill="x", padx=14, pady=(6, 12))

    # ---------------------------------------------------------------- map
    def _build_map(self, parent):
        frame = ctk.CTkFrame(parent, fg_color=COLORS["navy"], corner_radius=14)
        frame.grid(row=0, column=1, sticky="nsew")
        self.map_frame = frame
        self.canvas = MapCanvas(frame, self)
        self.canvas.pack(fill="both", expand=True, padx=6, pady=(6, 0))
        self._legend_expanded = True
        self.legend_strip = ctk.CTkFrame(frame, fg_color="#0B1F3A", corner_radius=8, height=72)
        self._fill_legend(self.legend_strip, compact=True)
        self.legend_strip.pack(fill="x", padx=6, pady=(4, 6))
        self.legend_overlay = ctk.CTkFrame(frame, fg_color="#0B1F3A", corner_radius=10,
                                           border_width=1, border_color="#1E3A8A")
        ov_head = ctk.CTkFrame(self.legend_overlay, fg_color="transparent")
        ov_head.pack(fill="x", padx=8, pady=(4, 0))
        ctk.CTkLabel(ov_head, text="LEGEND & ABBREVIATIONS", font=(FONT, 10, "bold"),
                     text_color="white").pack(side="left")
        ctk.CTkButton(ov_head, text="▾", width=28, height=22, fg_color="#1E3A8A",
                      command=self._toggle_legend_overlay).pack(side="right")
        self.legend_overlay_body = ctk.CTkFrame(self.legend_overlay, fg_color="transparent")
        self._fill_legend(self.legend_overlay_body, compact=True)
        self.legend_overlay_body.pack(fill="x", padx=6, pady=(0, 6))
        # floating zoom controls
        zc = ctk.CTkFrame(frame, fg_color="#0B1F3A", corner_radius=10)
        zc.place(relx=1.0, x=-16, y=16, anchor="ne")
        zb = dict(width=34, height=30, fg_color="#1E3A8A", hover_color="#2563EB", font=(FONT, 15, "bold"))
        ctk.CTkButton(zc, text="+", command=lambda: self.zoom(1.25), **zb).pack(padx=4, pady=(4, 2))
        ctk.CTkButton(zc, text="−", command=lambda: self.zoom(0.8), **zb).pack(padx=4, pady=2)
        ctk.CTkButton(zc, text="⟳", command=self.reset_view, **zb).pack(padx=4, pady=(2, 4))
        self.zoom_lbl = ctk.CTkLabel(frame, text="100%", fg_color="#0B1F3A", text_color="white",
                                     corner_radius=6, font=(FONT, 10, "bold"), width=48)
        self.zoom_lbl.place(relx=1.0, x=-16, y=134, anchor="ne")
        frame.bind("<Configure>", lambda e: self._layout_legend())

    def _fill_legend(self, parent, compact=True):
        entries = [
            ("●", COLORS["green"], "Start"),
            ("●", COLORS["red"], "Destination"),
            ("━", "#00E676", "Selected route"),
            ("━", COLORS["alt"], "Alternative route"),
            ("●", "#FACC15", "Currently processing"),
            ("●", "#3B82F6", "Visited"),
            ("○", "#A855F7", "In queue/stack/heap"),
        ]
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=6, pady=(4, 0))
        ctk.CTkLabel(row, text="LEGEND", font=(FONT, 10, "bold"),
                     text_color="#93C5FD").pack(side="left", padx=(0, 8))
        for sym, col, txt in entries:
            cell = ctk.CTkFrame(row, fg_color="transparent")
            cell.pack(side="left", padx=4)
            ctk.CTkLabel(cell, text=sym, text_color=col, font=(FONT, 12, "bold")).pack(side="left")
            ctk.CTkLabel(cell, text=txt, text_color="#E2E8F0", font=(FONT, 9)).pack(side="left", padx=(2, 0))
        abbr = ("ABBREVIATIONS  ·  m = metres  ·  V = vertices (buildings)  ·  E = edges (roads)  ·  "
                "BFS = Breadth-First Search  ·  DFS = Depth-First Search  ·  FIFO / LIFO  ·  "
                "Min-heap  ·  ∞ = not yet reached  ·  N = North")
        ctk.CTkLabel(parent, text=abbr, font=(FONT, 9), text_color="#94A3B8",
                     wraplength=900 if compact else 360, justify="left", anchor="w").pack(
            fill="x", padx=8, pady=(2, 6))

    def _toggle_legend_overlay(self):
        self._legend_expanded = not self._legend_expanded
        if self._legend_expanded:
            self.legend_overlay_body.pack(fill="x", padx=6, pady=(0, 6))
        else:
            self.legend_overlay_body.pack_forget()

    def _layout_legend(self):
        h = self.map_frame.winfo_height()
        if h < 420:
            if self.legend_strip.winfo_ismapped():
                self.legend_strip.pack_forget()
            if not self.legend_overlay.winfo_ismapped():
                self.legend_overlay.place(relx=0.0, rely=1.0, x=12, y=-12, anchor="sw")
        else:
            if self.legend_overlay.winfo_ismapped():
                self.legend_overlay.place_forget()
            if not self.legend_strip.winfo_ismapped():
                self.legend_strip.pack(fill="x", padx=6, pady=(4, 6))

    # ---------------------------------------------------------------- right
    def _build_right(self, parent):
        right = ctk.CTkFrame(parent, fg_color="transparent", width=400)
        right.grid(row=0, column=2, sticky="ns", padx=(10, 0))
        right.grid_propagate(False)
        right.pack_propagate(False)

        # status card
        st = make_card(right, "ROUTE STATUS")
        st.pack(fill="x", pady=(0, 8))
        self.status_big = ctk.CTkLabel(st, text="●  Ready", font=(FONT, 17, "bold"),
                                       text_color=COLORS["muted"], anchor="w")
        self.status_big.pack(fill="x", padx=14)
        self.status_msg = ctk.CTkLabel(st, text="Select source, destination and algorithm.",
                                       font=(FONT, 11), text_color=COLORS["muted"], anchor="w",
                                       justify="left", wraplength=360)
        self.status_msg.pack(fill="x", padx=14, pady=(0, 10))

        self.tabs = ctk.CTkTabview(right, fg_color=COLORS["card"], segmented_button_selected_color=COLORS["navy"],
                                   segmented_button_selected_hover_color=COLORS["navy_2"],
                                   border_width=1, border_color=COLORS["border"], corner_radius=12)
        self.tabs.pack(fill="both", expand=True)
        for name in ("Route", "Compare", "Graph", "Learn"):
            self.tabs.add(name)
        self._build_route_tab(self.tabs.tab("Route"))
        self._build_compare_tab(self.tabs.tab("Compare"))
        self._build_graph_tab(self.tabs.tab("Graph"))
        self._build_learn_tab(self.tabs.tab("Learn"))

    def _build_route_tab(self, tab):
        self.live_card = ctk.CTkFrame(tab, fg_color="#F8FAFC", corner_radius=10, border_width=1,
                                      border_color=COLORS["border"])
        ctk.CTkLabel(self.live_card, text="LIVE STEP", font=(FONT, 11, "bold"),
                     text_color=COLORS["navy"], anchor="w").pack(fill="x", padx=12, pady=(8, 0))
        self.live_lbl = ctk.CTkLabel(self.live_card, text="Step — of —\nCurrent node: —\nFrontier: —",
                                     font=(FONT, 11), text_color=COLORS["text"], anchor="w",
                                     justify="left", wraplength=360)
        self.live_lbl.pack(fill="x", padx=12, pady=(0, 8))
        holder, self.route_txt = with_scrollbar(tab, lambda m: make_text(m))
        holder.pack(fill="both", expand=True)
        self.live_card.pack(fill="x", pady=(6, 0), after=holder)
        # location details (map click)
        self.loc_card = ctk.CTkFrame(tab, fg_color="#F8FAFC", corner_radius=10, border_width=1,
                                     border_color=COLORS["border"])
        self.loc_title = ctk.CTkLabel(self.loc_card, text="", font=(FONT, 13, "bold"),
                                      text_color=COLORS["navy"], anchor="w")
        self.loc_title.pack(fill="x", padx=12, pady=(8, 0))
        self.loc_body = ctk.CTkLabel(self.loc_card, text="", font=(FONT, 11), text_color=COLORS["text"],
                                     anchor="w", justify="left")
        self.loc_body.pack(fill="x", padx=12)
        row = ctk.CTkFrame(self.loc_card, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=(4, 8))
        ctk.CTkButton(row, text="Set as Source", height=28, width=110, fg_color=COLORS["green"],
                      hover_color="#15803D", command=lambda: self._set_from_card("src")).pack(side="left")
        ctk.CTkButton(row, text="Set as Destination", height=28, width=130, fg_color=COLORS["red"],
                      hover_color="#B91C1C", command=lambda: self._set_from_card("dst")).pack(side="left", padx=6)
        ctk.CTkButton(row, text="✕", height=28, width=28, fg_color="#E2E8F0", text_color=COLORS["text"],
                      hover_color="#CBD5E1", command=self._hide_loc_card).pack(side="right")
        self._show_welcome()

    def _build_compare_tab(self, tab):
        sf = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        sf.pack(fill="both", expand=True)
        self.cmp_title = ctk.CTkLabel(sf, text="ALGORITHM COMPARISON – BFS · DFS · Dijkstra",
                                      font=(FONT, 13, "bold"), text_color=COLORS["navy"], anchor="w")
        self.cmp_title.pack(fill="x", pady=(2, 0))
        self.cmp_sub = ctk.CTkLabel(sf, text="Select a source and destination.", font=(FONT, 11),
                                    text_color=COLORS["muted"], anchor="w", wraplength=340, justify="left")
        self.cmp_sub.pack(fill="x")
        row = ctk.CTkFrame(sf, fg_color="transparent")
        row.pack(fill="x", pady=6)
        ctk.CTkButton(row, text="Run Comparison", height=30, width=140, fg_color=COLORS["navy"],
                      command=self.update_compare).pack(side="left")
        ctk.CTkButton(row, text="Show both on map", height=30, width=140, fg_color="#0EA5E9",
                      hover_color="#0284C7", command=self.show_compare_on_map).pack(side="left", padx=6)

        self.cmp_winner = ctk.CTkLabel(sf, text="", font=(FONT, 12, "bold"), text_color="#14532D",
                                       fg_color="#DCFCE7", corner_radius=8, wraplength=330,
                                       justify="left", anchor="w")
        self.cmp_winner.pack(fill="x", pady=4, ipady=6, ipadx=6)
        self.cmp_table = ctk.CTkFrame(sf, fg_color="#F8FAFC", corner_radius=10, border_width=1,
                                      border_color=COLORS["border"])
        self.cmp_table.pack(fill="x", pady=4)
        self.cmp_verdict = ctk.CTkLabel(sf, text="", font=(FONT, 11, "bold"), text_color="#9A3412",
                                        fg_color="#FFF7ED", corner_radius=8, wraplength=330,
                                        justify="left", anchor="w")
        self.cmp_verdict.pack(fill="x", pady=6, ipady=4, ipadx=6)
        self.cmp_chart = tk.Canvas(sf, height=150, bg="#FFFFFF", highlightthickness=0)
        self.cmp_chart.pack(fill="x", pady=4)
        ctk.CTkButton(sf, text="Show weighted vs unweighted example", height=30, fg_color="#0EA5E9",
                      hover_color="#0284C7", command=self.show_graph_type_example).pack(fill="x", pady=8)
        self._gt_example = None
        self._fill_graph_type_text()

    def _build_graph_tab(self, tab):
        info = ctk.CTkFrame(tab, fg_color="#F8FAFC", corner_radius=10, border_width=1,
                            border_color=COLORS["border"])
        info.pack(fill="x", pady=(2, 6))
        ctk.CTkLabel(info, text="HOW THE TRAVERSAL IS DONE", font=(FONT, 12, "bold"),
                     text_color=COLORS["navy"], anchor="w").pack(fill="x", padx=12, pady=(8, 2))
        self.ginfo_rows = {}
        grid = ctk.CTkFrame(info, fg_color="transparent")
        grid.pack(fill="x", padx=12, pady=(0, 8))
        for i, key in enumerate(["Nodes", "Connections", "Graph Type",
                                 "Representation", "Algorithms"]):
            ctk.CTkLabel(grid, text=key + ":", font=(FONT, 11, "bold"), text_color=COLORS["muted"],
                         anchor="w").grid(row=i, column=0, sticky="w", pady=1)
            v = ctk.CTkLabel(grid, text="", font=(FONT, 11), text_color=COLORS["text"], anchor="w")
            v.grid(row=i, column=1, sticky="w", padx=10, pady=1)
            self.ginfo_rows[key] = v
        holder, self.adj_txt = with_scrollbar(tab, lambda m: make_text(m, mono=True, height=16))
        holder.pack(fill="both", expand=True)
        self.graph_route_lbl = ctk.CTkLabel(tab, text="Final route: —", font=(FONT, 11, "bold"),
                                            text_color=COLORS["navy"], wraplength=360, justify="left",
                                            anchor="w")
        self.graph_route_lbl.pack(fill="x", padx=8, pady=(4, 6))

    def _build_learn_tab(self, tab):
        sf = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        sf.pack(fill="both", expand=True)
        cards = [
            ("BFS", COLORS["blue"],
             "Idea: explore level by level (fewest roads first).",
             "Queue (FIFO)",
             "O(V + E)", "O(V)",
             "When the number of hops matters more than metres.",
             "No – ignores weights.",
             "First arrival uses the fewest edges because closer levels finish first."),
            ("DFS", "#7C3AED",
             "Idea: go as deep as possible, then backtrack.",
             "Stack (LIFO)",
             "O(V + E)", "O(V)",
             "When you only need some path, not the shortest.",
             "No – first path found, no optimality.",
             "Complete on a finite graph, but the path it returns is not guaranteed shortest."),
            ("Dijkstra", COLORS["green"],
             "Idea: always expand the closest unfinished building.",
             "Min-heap",
             "O((V + E) log V)", "O(V)",
             "When road lengths differ and you want the shortest distance.",
             "Yes – on non-negative weights.",
             "Once a node is popped its distance is final because weights are non-negative."),
        ]
        for name, color, idea, ds, t, s, when, opt, corr in cards:
            c = ctk.CTkFrame(sf, fg_color="#FFFFFF", corner_radius=10, border_width=2, border_color=color)
            c.pack(fill="x", pady=4)
            ctk.CTkLabel(c, text=name, font=(FONT, 14, "bold"), text_color=color,
                         anchor="w").pack(fill="x", padx=10, pady=(8, 2))
            for label, val in [
                ("Idea", idea), ("Data structure", ds), ("Time", t), ("Space", s),
                ("When to use", when), ("Optimal on weighted graphs?", opt),
                ("Correctness", corr),
            ]:
                ctk.CTkLabel(c, text=label, font=(FONT, 9, "bold"), text_color=COLORS["muted"],
                             anchor="w").pack(fill="x", padx=10)
                ctk.CTkLabel(c, text=val, font=(FONT, 11), text_color=COLORS["text"],
                             anchor="w", wraplength=330, justify="left").pack(fill="x", padx=10, pady=(0, 4))
            ctk.CTkLabel(c, text="").pack(pady=2)

    def _build_statusbar(self):
        bar = ctk.CTkFrame(self, fg_color="#E2E8F0", corner_radius=0, height=28)
        bar.pack(fill="x", side="bottom", pady=(10, 0))
        self.bar_msg = ctk.CTkLabel(bar, text="Ready.", font=(FONT, 11), text_color=COLORS["text"], anchor="w")
        self.bar_msg.pack(side="left", padx=12)
        self.bar_info = ctk.CTkLabel(bar, text="", font=(FONT, 11), text_color=COLORS["muted"])
        self.bar_info.pack(side="right", padx=12)

    def _initial_render(self):
        self.canvas.render()
        self.refresh_graph_info()
        if self.canvas.load_error:
            self.set_status("error", "Map not loaded", MAP_MISSING_MSG)
            self.bar_msg.configure(text=MAP_MISSING_MSG)
        else:
            self.bar_msg.configure(text="Campus map loaded. Select a source and destination to begin.")

    # ================================================================ helpers
    def get_selection(self):
        s, d = self.src_var.get(), self.dst_var.get()
        return (None if s == SRC_PLACEHOLDER else s), (None if d == DST_PLACEHOLDER else d)

    def set_status(self, kind, title, msg):
        styles = {
            "idle": ("●  ", COLORS["muted"]),
            "found": ("✓  ", COLORS["green"]),
            "rerouted": ("⚠  ", "#EA580C"),
            "blocked": ("⚠  ", COLORS["red"]),
            "none": ("✕  ", COLORS["red"]),
            "error": ("⚠  ", COLORS["red"]),
            "info": ("ℹ  ", COLORS["accent"]),
            "anim": ("◔  ", "#7C3AED"),
        }
        icon, color = styles.get(kind, styles["idle"])
        self.status_big.configure(text=icon + title, text_color=color)
        self.status_msg.configure(text=msg)
        self.bar_msg.configure(text=f"{title} – {msg}")

    def refresh_graph_info(self):
        info = self.nav.graph_info()
        self.ginfo_rows["Nodes"].configure(text=str(info["nodes"]))
        self.ginfo_rows["Connections"].configure(text=str(info["edges"]))
        self.ginfo_rows["Graph Type"].configure(text=info["type"])
        self.ginfo_rows["Representation"].configure(text=info["representation"])
        self.ginfo_rows["Algorithms"].configure(text="BFS · DFS · Dijkstra")
        self._write_graph_steps(None, None)
        self.bar_info.configure(text=f"V = {info['nodes']}   ·   E = {info['edges']}   ·   "
                                     f"Weighted Undirected Graph")
        if self.viva:
            self.viva.show_graph()

    def _show_welcome(self):
        write_rich(self.route_txt, [
            ("ROUTE INFORMATION\n", "h1"),
            ("How to use\n", "h2"),
            ("Select Source and Destination  →  Choose Algorithm  →  Find Route  →  Animate / Explanation\n\n",
             "route"),
            ("1. Choose a SOURCE and a DESTINATION (or click buildings on the map).\n", "value"),
            ("   The two endpoints become the start and goal vertices.\n", "muted"),
            ("2. Pick BFS, DFS or Dijkstra.\n", "value"),
            ("   BFS uses a FIFO queue · DFS a LIFO stack · Dijkstra a min-heap.\n", "muted"),
            ("3. Press FIND ROUTE – the route is drawn on the campus map.\n", "value"),
            ("   The chosen algorithm walks the adjacency list and rebuilds the path from parents.\n", "muted"),
            ("4. Press FIND ALTERNATIVE for the second-best simple route.\n", "value"),
            ("   Each best-route edge is removed on a copy of the graph; the cheapest distinct path is kept.\n",
             "muted"),
            ("5. Use ANIMATE ALGORITHM or EXPLANATION to see the algorithm step by step.\n", "value"),
            ("   Exploration follows roads, then a marker traces the final route.\n", "muted"),
            ("\nTip: try Academic Block → Medical Centre with BFS and then Dijkstra.\n", "note"),
        ])
        self._set_live_step(None)

    def _stop_animation(self):
        if self.anim_job:
            self.after_cancel(self.anim_job)
            self.anim_job = None
        self.anim_playing = False
        self.pause_btn.configure(text="⏸ PAUSE")

    def _cancel_animation_run(self):
        self.anim_gen += 1
        self._stop_animation()
        self.canvas.clear_anim_overlay()
        self.anim_phase = "A"
        self.anim_event_i = 0
        self.anim_step_target = None

    # ================================================================ events
    def on_selection_change(self):
        src, dst = self.get_selection()
        self.canvas.source, self.canvas.target = src, dst
        self.canvas.render()
        if src and dst and src != dst:
            self.update_compare()
        elif src and dst:
            self.set_status("error", "Invalid selection", "Source and destination cannot be the same.")

    def on_algorithm_change(self):
        a = self.algo_var.get()
        if self.anim_playing or self.anim_resp:
            self._cancel_animation_run()
            self.canvas.node_states, self.canvas.visit_order, self.canvas.tree_edges = {}, [], []
            self.canvas.render()
            self.step_lbl.configure(text="Algorithm changed – previous animation cancelled.")
        self.bar_msg.configure(text=f"{a}: {ALGO_DESC[a]}")

    def swap_locations(self):
        s, d = self.src_var.get(), self.dst_var.get()
        self.src_var.set(d if d != DST_PLACEHOLDER else SRC_PLACEHOLDER)
        self.dst_var.set(s if s != SRC_PLACEHOLDER else DST_PLACEHOLDER)
        self.on_selection_change()

    def on_node_click(self, node):
        self.canvas.selected = node
        src, dst = self.get_selection()
        auto = ""
        if not src:
            self.src_var.set(node)
            auto = "  → set as SOURCE"
        elif not dst and node != src:
            self.dst_var.set(node)
            auto = "  → set as DESTINATION"
        conns = self.nav.connections(node)
        lines = ["Connected Locations:"]
        for v, w, _blocked in conns:
            lines.append(f"   • {v} — {w} m")
        self.loc_title.configure(text=f"📍 {node}  ({short(node)})")
        self.loc_body.configure(text="\n".join(lines))
        self.loc_card.pack(fill="x", pady=(6, 0))
        self.tabs.set("Route")
        self.bar_msg.configure(text=f"{node}: {len(conns)} connected locations{auto}")
        self.on_selection_change()

    def _set_from_card(self, which):
        node = self.canvas.selected
        if not node:
            return
        (self.src_var if which == "src" else self.dst_var).set(node)
        self.on_selection_change()

    def _hide_loc_card(self):
        self.loc_card.pack_forget()
        self.canvas.selected = None
        self.canvas.render()

    def zoom(self, factor):
        self.canvas.zoom_by(factor)
        self.update_zoom_label()

    def reset_view(self):
        self.canvas.reset_view()
        self.update_zoom_label()

    def update_zoom_label(self):
        self.zoom_lbl.configure(text=f"{int(round(self.canvas.zoom * 100))}%")

    # ================================================================ routing
    def _validate_or_warn(self, src, dst):
        err = self.nav.validate(src, dst)
        if err:
            self.set_status("error", "Invalid selection", err)
            messagebox.showwarning("Campus Navigation", err, parent=self)
        return err

    def find_route(self):
        self._stop_animation()
        src, dst = self.get_selection()
        if self._validate_or_warn(src, dst):
            return
        algo = self.algo_var.get()
        resp = self.nav.find_route(src, dst, algo)
        self.current_resp, self.current_kind = resp, "route"
        self.anim_resp, self.anim_index = resp, len(resp["result"]["steps"]) - 1
        self._display_route(resp)
        self.update_compare()
        if self.viva:
            self.viva.update_view(self.anim_resp, self.anim_index, False)

    def _display_route(self, resp):
        res = resp["result"]
        algo = res["algorithm"]
        c = self.canvas
        c.source, c.target = res["source"], res["target"]
        c.tree_edges = []
        c.node_states = {v: "visited" for v in res["visited"]}
        c.visit_order = list(res["visited"])
        c.routes = []
        self.main_paths = []
        if resp["status"] == "none":
            if resp.get("original") and resp["original"]["found"]:
                c.routes.append({"path": resp["original"]["path"], "color": "#94A3B8",
                                 "width": 5, "kind": "dim"})
            self.set_status("none", "No Route Available", resp["message"])
        elif resp["status"] == "rerouted":
            c.routes.append({"path": resp["original"]["path"], "color": "#94A3B8", "width": 5, "kind": "dim"})
            c.routes.append({"path": res["path"], "color": COLORS["alt"], "width": 7, "kind": "alt"})
            self.main_paths = [res["path"]]
            blocked = ", ".join(fmt_edge(e) for e in resp["blocked_on_route"])
            self.set_status("rerouted", "Route Blocked",
                            f"{blocked} is blocked. Alternative route found automatically "
                            f"({fmt_distance(res['distance'])}).")
        else:
            c.routes.append({"path": res["path"], "color": ROUTE_COLORS[algo], "width": 8, "kind": "main"})
            self.main_paths = [res["path"]]
            self.set_status("found", "Route Found", resp["message"])
        c.render()
        self._write_route_info(resp)
        self.tabs.set("Route")

    def _write_route_info(self, resp):
        res = resp["result"]
        algo = res["algorithm"]
        ch = [("ROUTE INFORMATION\n", "h1"),
              ("SOURCE\n", "label"), (res["source"] + "\n", "value"),
              ("DESTINATION\n", "label"), (res["target"] + "\n", "value"),
              ("ALGORITHM\n", "label"), (f"{algo}", "value"),
              (f"   ({COMPLEXITY[algo]['structure']})\n", "muted")]
        if resp["status"] == "rerouted":
            o = resp["original"]
            ch += [("PRIMARY ROUTE (original graph)\n", "label"),
                   (fmt_path_inline(o["path"]) + f"   [{fmt_distance(o['distance'])}]\n", "muted"),
                   ("BLOCKED\n", "label"),
                   ("\n".join("⛔ " + fmt_edge(e) for e in resp["blocked_on_route"]) + "\n", "red"),
                   ("ALTERNATIVE ROUTE\n", "label")]
        else:
            ch += [("ROUTE\n" if algo != "DFS" else "TRAVERSAL ROUTE\n", "label")]
        if res["found"]:
            for i, p in enumerate(res["path"]):
                ch.append((("   ↓\n" if i else ""), "arrow"))
                ch.append((f"{p}\n", "route"))
            ch += [("NUMBER OF EDGES\n", "label"), (f"{res['edges']}\n", "big")]
            if algo == "BFS":
                ch += [("TOTAL DISTANCE (computed after the search)\n", "label"),
                       (f"{fmt_distance(res['distance'])}\n", "big")]
            else:
                ch += [("TOTAL DISTANCE\n", "label"), (f"{fmt_distance(res['distance'])}\n", "big")]
        else:
            ch += [("—\n", "value")]
        ch += [("NUMBER OF NODES VISITED\n", "label"), (f"{len(res['visited'])}\n", "big"),
               ("Visit order: " + fmt_path_inline(res["visited"], use_codes=True) + "\n", "muted"),
               ("EXECUTION TIME\n", "label"), (fmt_ms(res["time_ms"]) + "\n", "value"),
               ("ROUTE STATUS\n", "label")]
        tag = {"found": "green", "rerouted": "orange", "none": "red"}[resp["status"]]
        ch += [(resp["message"] + "\n\n", tag)]
        notes = {
            "BFS": "BFS optimises the NUMBER OF EDGES (hops), not the weighted distance. "
                   "The distance above is calculated afterwards from the route found.",
            "DFS": "⚠ DFS does NOT guarantee the shortest route. It explores deeply and "
                   "returns the first route it reaches.",
            "Dijkstra": "Dijkstra uses actual road lengths and guarantees the minimum total "
                        "distance (all weights are non-negative).",
        }
        ch += [(notes[algo] + "\n", "note")]
        write_rich(self.route_txt, ch)

    def find_alternative(self):
        self._cancel_animation_run()
        src, dst = self.get_selection()
        if self._validate_or_warn(src, dst):
            return
        algo = self.algo_var.get()
        resp = self.nav.find_alternative(src, dst, algo)
        self.current_resp, self.current_kind = resp, "alternative"
        c = self.canvas
        c.source, c.target = src, dst
        c.node_states, c.visit_order, c.tree_edges, c.routes = {}, [], [], []
        primary, alt = resp["primary"], resp["alternative"]
        if primary and primary["found"]:
            c.routes.append({"path": primary["path"], "color": ROUTE_COLORS.get(algo, "#00E676"),
                             "width": 8, "kind": "main"})
        if alt:
            c.routes.append({"path": alt["path"], "color": COLORS["alt"], "width": 7, "kind": "alt"})
            c.node_states = {v: "visited" for v in alt["visited"]}
            c.visit_order = list(alt["visited"])
            self.main_paths = [primary["path"], alt["path"]] if primary and primary["found"] else [alt["path"]]
            extra = resp.get("extra_distance", 0)
            extra_txt = (f"+{extra:g} m longer" if extra > 0
                         else ("same distance" if extra == 0 else f"{extra:g} m shorter"))
            self.set_status("found", "Alternative Route Found",
                            f"{fmt_path_inline(alt['path'], use_codes=True)}  ·  "
                            f"{fmt_distance(alt['distance'])}  ·  {extra_txt}")
        else:
            self.main_paths = [primary["path"]] if primary and primary["found"] else []
            self.set_status("none", "No Alternative Route", resp["message"])
        c.render()

        ch = [("ALTERNATIVE ROUTE  (second-best simple path)\n", "h1"),
              ("SOURCE → DESTINATION\n", "label"), (f"{src} → {dst}\n", "value"),
              ("ALGORITHM\n", "label"),
              (f"{algo} on a copy of the graph with each best-route edge removed in turn\n", "value"),
              ("BEST ROUTE\n", "label")]
        if primary and primary["found"]:
            ch += [(fmt_path_inline(primary["path"]) + "\n", "route"),
                   (f"Distance: {fmt_distance(primary['distance'])} · {primary['edges']} edges\n", "muted")]
        else:
            ch += [("—\n", "value")]
        ch += [("SECOND-BEST ROUTE\n", "label")]
        if alt:
            for i, p in enumerate(alt["path"]):
                ch.append((("   ↓\n" if i else ""), "arrow"))
                ch.append((f"{p}\n", "route"))
            extra = resp.get("extra_distance", 0)
            extra_txt = (f"+{extra:g} m longer" if extra > 0
                         else ("same distance" if extra == 0 else f"{extra:g} m shorter"))
            ch += [("ALTERNATIVE DISTANCE\n", "label"), (f"{fmt_distance(alt['distance'])}\n", "big"),
                   ("VS BEST ROUTE\n", "label"), (extra_txt + "\n", "value"),
                   ("NUMBER OF EDGES\n", "label"), (f"{alt['edges']}\n", "value")]
        else:
            ch += [(resp["message"] + "\n", "red")]
        ch += [("\nROUTE STATUS\n", "label"),
               (resp["message"] + "\n", "orange" if alt else "red")]
        write_rich(self.route_txt, ch)
        self.tabs.set("Route")

    def clear_route(self):
        self._stop_animation()
        c = self.canvas
        c.routes, c.node_states, c.visit_order, c.tree_edges = [], {}, [], []
        self.main_paths, self.current_resp, self.anim_resp = [], None, None
        c.render()
        self.step_lbl.configure(text="Watch the algorithm explore the campus step by step.")
        self.set_status("idle", "Ready", "Route cleared. Select source, destination and algorithm.")
        self._show_welcome()
        if self.viva:
            self.viva.update_view(None, 0, False)

    # ================================================================ blocking
    def block_selected_road(self):
        edge = self.road_map.get(self.road_var.get())
        if not edge:
            return
        if self.nav.graph.is_blocked(*edge):
            self.bar_msg.configure(text=f"{fmt_edge(edge)} is already blocked.")
            return
        self.nav.block_road(*edge)
        self._after_block_change(edge)

    def _after_block_change(self, edge):
        self.refresh_graph_info()
        self.canvas.render()
        if self.nav.graph.is_blocked(*edge):
            hit = [p for p in self.main_paths if edge_key(*edge) in path_edges(p)]
            if hit:
                self.set_status("blocked", "Route Blocked",
                                f"The displayed route uses {fmt_edge(edge)}. "
                                f"Press FIND ALTERNATIVE to re-route.")
            else:
                self.set_status("info", "Road Blocked", f"{fmt_edge(edge)} is now unavailable (red dashed).")
        else:
            self.set_status("info", "Road Reopened", f"{fmt_edge(edge)} is available again.")
        src, dst = self.get_selection()
        if src and dst and src != dst:
            self.update_compare()

    def restore_roads(self):
        n = len(self.nav.blocked_roads())
        self.nav.restore_roads()
        self.refresh_graph_info()
        self.canvas.render()
        self.set_status("info", "Roads Restored",
                        f"{n} blocked road(s) restored – original campus graph is active.")
        src, dst = self.get_selection()
        if src and dst and src != dst:
            self.update_compare()

    # ================================================================ compare
    def open_comparison(self):
        self.tabs.set("Compare")
        self.update_compare()

    def update_compare(self):
        for w in self.cmp_table.winfo_children():
            w.destroy()
        src, dst = self.get_selection()
        resp = self.nav.compare(src, dst)
        if not resp["ok"]:
            self.cmp_sub.configure(text=resp["error"])
            self.cmp_verdict.configure(text="")
            return None
        self.cmp_sub.configure(text=f"{src}  →  {dst}"
                               + ("   (blocked roads excluded)" if self.nav.graph.blocked else ""))
        headers = ["Algorithm", "Path", "Edges", "Distance", "Visited"]
        for j, h in enumerate(headers):
            ctk.CTkLabel(self.cmp_table, text=h, font=(FONT, 10, "bold"), text_color="white",
                         fg_color=COLORS["navy"], corner_radius=0).grid(row=0, column=j, sticky="nsew")
        self.cmp_table.grid_columnconfigure(1, weight=1)
        for i, key in enumerate(("bfs", "dijkstra"), start=1):
            r = resp[key]
            name = r["algorithm"]
            vals = [name, fmt_path_inline(r["path"], use_codes=True) if r["found"] else "No route",
                    str(r["edges"]) if r["found"] else "—", fmt_distance(r["distance"]),
                    str(len(r["visited"]))]
            for j, v in enumerate(vals):
                ctk.CTkLabel(self.cmp_table, text=v, font=(FONT, 11, "bold" if j == 0 else "normal"),
                             text_color=ALGO_COLORS[name] if j == 0 else COLORS["text"],
                             wraplength=150 if j == 1 else 0, justify="left").grid(
                    row=i, column=j, sticky="w", padx=5, pady=4)
        b, d = resp["bfs"], resp["dijkstra"]
        if not b["found"]:
            verdict = "No route available between the selected locations."
        elif resp["same_path"]:
            verdict = (f"Both algorithms choose the SAME route here "
                       f"({b['edges']} edges, {fmt_distance(b['distance'])}).")
        else:
            verdict = (f"Different routes!  BFS uses {b['edges']} edges ({fmt_distance(b['distance'])}); "
                       f"Dijkstra uses {d['edges']} edges ({fmt_distance(d['distance'])}). "
                       f"Dijkstra saves {fmt_distance(b['distance'] - d['distance'])} – "
                       f"fewer edges does not mean shorter distance.")
        self.cmp_verdict.configure(text=verdict)
        self._cmp_resp = resp
        return resp

    def show_compare_on_map(self):
        resp = self.update_compare()
        if not resp:
            src, dst = self.get_selection()
            self._validate_or_warn(src, dst)
            return
        self._show_two_routes(resp["bfs"], resp["dijkstra"])

    def _show_two_routes(self, b, d):
        self._stop_animation()
        c = self.canvas
        c.source, c.target = b["source"], b["target"]
        c.node_states, c.visit_order, c.tree_edges = {}, [], []
        c.routes = []
        if d["found"]:
            c.routes.append({"path": d["path"], "color": ROUTE_COLORS["Dijkstra"], "width": 8, "kind": "main"})
        if b["found"]:
            c.routes.append({"path": b["path"], "color": ROUTE_COLORS["BFS"], "width": 4, "kind": "main"})
        self.main_paths = [p for p in (b["path"], d["path"]) if p]
        c.render()
        self.set_status("info", "Comparison on map",
                        f"Blue = BFS ({b['edges']} edges, {fmt_distance(b['distance'])})   ·   "
                        f"Green = Dijkstra ({d['edges']} edges, {fmt_distance(d['distance'])})")

    def _fill_graph_type_text(self):
        ex = self.nav.disagreement_example()
        self._gt_example = ex
        ch = [("UNWEIGHTED GRAPH\n", "h2"),
              ("All connections are considered equal (every road = 1 step). "
               "BFS can find the minimum-edge path.\n", "value"),
              ("WEIGHTED GRAPH\n", "h2"),
              ("Connections have different distances. Dijkstra finds the minimum-distance path.\n", "value")]
        if ex:
            b, d = ex["bfs"], ex["dijkstra"]
            ch += [("\nEXAMPLE  ", "h2"), (f"{ex['source']} → {ex['target']}\n", "value"),
                   ("Route A  (chosen by BFS)\n", "blue"),
                   (fmt_path_inline(b["path"]) + "\n", "route"),
                   (f"{b['edges']} edges   ·   {fmt_distance(b['distance'])}\n", "mono"),
                   ("Route B  (chosen by Dijkstra)\n", "green"),
                   (fmt_path_inline(d["path"]) + "\n", "route"),
                   (f"{d['edges']} edges   ·   {fmt_distance(d['distance'])}\n\n", "mono"),
                   ("BFS chooses Route A because it has FEWER EDGES.\n"
                    "Dijkstra chooses Route B because it has LOWER TOTAL DISTANCE.\n", "note")]
        else:
            ch += [("\nWith the current distances BFS and Dijkstra agree for every pair.\n", "muted")]
        write_rich(self.gt_txt, ch)

    def show_graph_type_example(self):
        ex = self._gt_example
        if not ex:
            return
        self.src_var.set(ex["source"])
        self.dst_var.set(ex["target"])
        self.update_compare()
        self._show_two_routes(ex["bfs"], ex["dijkstra"])

    # ================================================================ animation
    def _delay(self):
        # slider 0 = slow (1600 ms), 100 = fast (150 ms)
        return int(1600 - self.speed.get() * 14.5)

    def animate_algorithm(self):
        self._stop_animation()
        src, dst = self.get_selection()
        if self._validate_or_warn(src, dst):
            return
        resp = self.nav.find_route(src, dst, self.algo_var.get())
        self.anim_resp, self.anim_index = resp, 0
        self.current_resp, self.current_kind = resp, "route"
        self.canvas.routes = []
        self.main_paths = []
        self.set_status("anim", f"Animating {resp['result']['algorithm']}",
                        "Yellow = processing · Blue = visited · Purple = waiting in the data structure.")
        self.tabs.set("Route")
        self._anim_play()

    def _anim_play(self):
        self.anim_playing = True
        self.pause_btn.configure(text="⏸ PAUSE")
        self._anim_tick()

    def _anim_tick(self):
        self.anim_job = None
        if not self.anim_playing or not self.anim_resp:
            return
        steps = self.anim_resp["result"]["steps"]
        self.show_step(self.anim_index)
        if self.anim_index >= len(steps) - 1:
            self.anim_playing = False
            self.pause_btn.configure(text="⏸ PAUSE")
            if self.viva:
                self.viva.update_view(self.anim_resp, self.anim_index, False)
            return
        self.anim_index += 1
        self.anim_job = self.after(self._delay(), self._anim_tick)

    def show_step(self, i):
        resp = self.anim_resp
        if not resp:
            return
        res = resp["result"]
        steps = res["steps"]
        i = max(0, min(i, len(steps) - 1))
        self.anim_index = i
        step = steps[i]
        states = {v: "visited" for v in step["visited"]}
        frontier = ([v for _, v in step["frontier"]] if res["algorithm"] == "Dijkstra"
                    else step["frontier"])
        for v in frontier:
            states.setdefault(v, "frontier")
        if step["current"]:
            states[step["current"]] = "current"
        c = self.canvas
        c.source, c.target = res["source"], res["target"]
        c.node_states = states
        c.visit_order = list(step["visited"])
        c.tree_edges = [(p, v) for v, p in step["parents"].items() if p]
        last = i == len(steps) - 1
        if last:
            self._display_route(resp)            # final route + info panel
            c.tree_edges = [(p, v) for v, p in step["parents"].items() if p]
            c.render()
        else:
            c.routes = []
            self.main_paths = []
            c.render()
        self.step_lbl.configure(text=f"Step {i + 1}/{len(steps)} — {step['action']}")
        if self.viva:
            self.viva.update_view(resp, i, self.anim_playing)

    def toggle_pause(self):
        if not self.anim_resp:
            src, dst = self.get_selection()
            if self.nav.validate(src, dst) is None:
                self.animate_algorithm()
            else:
                self._validate_or_warn(src, dst)
            return
        if self.anim_playing:
            self._stop_animation()
            self.pause_btn.configure(text="▶ RESUME")
            self.set_status("anim", "Animation paused", self.step_lbl.cget("text"))
        else:
            if self.anim_index >= len(self.anim_resp["result"]["steps"]) - 1:
                self.anim_index = 0
            self._anim_play()
        if self.viva:
            self.viva.update_view(self.anim_resp, self.anim_index, self.anim_playing)

    def reset_animation(self):
        self._stop_animation()
        self.anim_index = 0
        c = self.canvas
        c.node_states, c.visit_order, c.tree_edges, c.routes = {}, [], [], []
        self.main_paths = []
        c.render()
        self.step_lbl.configure(text="Animation reset. Press ANIMATE ALGORITHM or RESUME to start.")
        if self.anim_resp:
            self.pause_btn.configure(text="▶ RESUME")
            self.set_status("idle", "Animation reset", "Press RESUME to replay the exploration.")
        if self.viva:
            self.viva.update_view(self.anim_resp, 0, False)

    def goto_step(self, i):
        if not self.anim_resp:
            self.prepare_viva()
            if not self.anim_resp:
                return
        self._stop_animation()
        self.show_step(i)

    # ================================================================ viva
    def open_viva(self):
        if self.viva is None or not self.viva.winfo_exists():
            self.viva = VivaWindow(self)
        else:
            self.viva.lift()
        if self.anim_resp:
            self.viva.update_view(self.anim_resp, self.anim_index, self.anim_playing)
        else:
            self.prepare_viva(silent=True)

    def prepare_viva(self, silent=False):
        src, dst = self.get_selection()
        err = self.nav.validate(src, dst)
        if err:
            if not silent:
                messagebox.showwarning("Viva Mode", err, parent=self.viva or self)
            if self.viva:
                self.viva.update_view(None, 0, False)
            return
        self._stop_animation()
        self.anim_resp = self.nav.find_route(src, dst, self.algo_var.get())
        self.current_resp, self.current_kind = self.anim_resp, "route"
        self.show_step(0)
        self.set_status("anim", "Viva Mode", "Use Next / Prev in the Viva window to step through the algorithm.")

    # =========================================================================
    # REPAIR BLOCK (prompt 2) – append-only.
    # The previous round left four members referenced but never defined
    # (next_step, _set_live_step, _write_graph_steps, gt_txt), which made the
    # app crash at start-up. They are defined here; no existing line changed.
    # =========================================================================
    @property
    def gt_txt(self):
        """Text widget for the weighted/unweighted example (Compare tab), created lazily."""
        w = self.__dict__.get("_gt_txt_widget")
        if w is None:
            w = make_text(self.cmp_title.master, height=14)
            w.pack(fill="x", pady=4)
            self.__dict__["_gt_txt_widget"] = w
        return w

    def _set_live_step(self, i):
        """Fill the LIVE STEP box for step index i (None = idle)."""
        resp = self.anim_resp
        if i is None or not resp:
            self.live_lbl.configure(text="Step — of —\nCurrent node: —\nFrontier: —")
            return
        res = resp["result"]
        steps = res["steps"]
        i = max(0, min(i, len(steps) - 1))
        step = steps[i]
        if res["algorithm"] == "Dijkstra":
            frontier = ", ".join(f"({d:g}, {short(v)})" for d, v in step["frontier"])
        else:
            frontier = ", ".join(short(v) for v in step["frontier"])
        self.live_lbl.configure(
            text=f"Step {i + 1} of {len(steps)}\n"
                 f"Current node: {step['current'] or '—'}\n"
                 f"Frontier: {frontier or '(empty)'}\n{step['action']}")

    def _write_graph_steps(self, resp, i):
        """Graph tab: traversal log up to step i (resp None = placeholder)."""
        if not resp:
            write_rich(self.adj_txt, [
                ("TRAVERSAL LOG\n", "h2"),
                ("Run Find Route, Animate or Next Step to see how the selected "
                 "algorithm walks the adjacency list, step by step.\n", "muted")])
            return
        res = resp["result"]
        steps = res["steps"]
        i = max(0, min(len(steps) - 1 if i is None else i, len(steps) - 1))
        ch = [(f"TRAVERSAL LOG – {res['algorithm']}\n", "h2"),
              (f"{res['source']} → {res['target']}\n\n", "muted")]
        for k in range(i + 1):
            ch.append((f"{k + 1:>2}. ", "monob"))
            ch.append((steps[k]["action"] + "\n", "orange" if k == i else "mono"))
        write_rich(self.adj_txt, ch)
        self.adj_txt.see("end")

    def next_step(self):
        """Advance the algorithm by exactly one step (prepares it if needed)."""
        src, dst = self.get_selection()
        resp = self.anim_resp
        stale = (not resp or resp["result"]["source"] != src or resp["result"]["target"] != dst
                 or resp["result"]["algorithm"] != self.algo_var.get())
        if stale:
            if self._validate_or_warn(src, dst):
                return
            self._cancel_animation_run()
            self.anim_resp = self.nav.find_route(src, dst, self.algo_var.get())
            self.current_resp, self.current_kind = self.anim_resp, "route"
            self.tabs.set("Route")
            self.set_status("anim", f"Stepping {self.algo_var.get()}",
                            "Press NEXT STEP to advance one step at a time.")
            self.show_step(0)
            return
        self._stop_animation()
        self.pause_btn.configure(text="▶ RESUME")
        last = len(resp["result"]["steps"]) - 1
        if self.anim_index >= last:
            self.set_status("anim", "Restarting steps", "Reached the end – starting again from step 1.")
            self.show_step(0)
        else:
            self.show_step(self.anim_index + 1)
