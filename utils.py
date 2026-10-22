"""
utils.py
========
Small shared helpers: formatting, colour palette, resource paths.
"""

import os
import sys

from campus_data import CODES

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MAP_PATH = os.path.join(BASE_DIR, "assets", "campus_map.png")
MAP_MISSING_MSG = "Campus map image not found. Place campus_map.png inside assets/."

# ---------------------------------------------------------------- palette
COLORS = {
    "navy": "#0B1F3A",
    "navy_2": "#132D52",
    "accent": "#2563EB",
    "bg": "#EEF2F7",
    "card": "#FFFFFF",
    "border": "#D8DEE9",
    "text": "#0F172A",
    "muted": "#64748B",
    "green": "#16A34A",
    "red": "#DC2626",
    "blue": "#2563EB",
    "orange": "#F97316",
    "yellow": "#FACC15",
    "route": "#00E676",       # bright route line
    "route_glow": "#0B3D2E",
    "alt": "#FF8C1A",
    "node": "#FFFFFF",
    "visited": "#3B82F6",
    "frontier": "#A855F7",
}

ALGO_COLORS = {"BFS": "#2563EB", "DFS": "#7C3AED", "Dijkstra": "#16A34A"}


def fmt_distance(d):
    if d is None or d == float("inf"):
        return "—"
    return f"{d:g} m"


def fmt_ms(ms):
    if ms < 1:
        return f"{ms * 1000:.1f} µs"
    return f"{ms:.3f} ms"


def short(name):
    return CODES.get(name, name)


def fmt_path_inline(path, use_codes=False):
    if not path:
        return "—"
    names = [short(p) for p in path] if use_codes else path
    return " → ".join(names)


def fmt_path_vertical(path):
    if not path:
        return "—"
    return "\n   ↓\n".join(path)


def fmt_edge(edge):
    u, v = edge
    return f"{u} ↔ {v}"


def resource_exists(path):
    return os.path.isfile(path)


def is_windows():
    return sys.platform.startswith("win")
