"""
campus_data.py
==============
All *static* campus information lives here so that it can be edited
without touching any algorithm or UI code.

    * LOCATIONS       – the vertices (V) of the graph
    * CORE_ROADS      – the 9 weighted, undirected edges given in the project brief
    * EXTRA_ROADS     – 2 additional roads that physically exist on the map
    * NODE_POSITIONS  – (x, y) pixel position of every building on campus_map.png
    * ROAD_WAYPOINTS  – poly-line that follows the drawn road for every edge

All coordinates are in ORIGINAL IMAGE PIXELS (campus_map.png = 1024 x 572).
The UI scales them automatically when the window is resized or zoomed.
"""

# ---------------------------------------------------------------------------
# 1. VERTICES  (short code -> full name)
# ---------------------------------------------------------------------------
LOCATIONS = {
    "A": "Administration Building",
    "L": "Library",
    "AC": "Academic Block",
    "LAB": "Laboratory",
    "C": "Cafeteria",
    "H": "Hostel",
    "P": "Parking",
    "M": "Medical Centre",
}

# Reverse lookup: full name -> short code
CODES = {name: code for code, name in LOCATIONS.items()}

# Display order used in drop-downs
LOCATION_ORDER = [
    "Administration Building",
    "Library",
    "Academic Block",
    "Laboratory",
    "Cafeteria",
    "Hostel",
    "Parking",
    "Medical Centre",
]

# ---------------------------------------------------------------------------
# 2. EDGES  (u, v, distance in metres) – weighted & undirected
# ---------------------------------------------------------------------------
# Exactly the sample distances from the project specification.
CORE_ROADS = [
    ("Academic Block", "Library", 120),
    ("Academic Block", "Laboratory", 80),
    ("Academic Block", "Administration Building", 150),
    ("Library", "Cafeteria", 100),
    ("Laboratory", "Cafeteria", 130),
    ("Laboratory", "Hostel", 200),
    ("Cafeteria", "Hostel", 100),
    ("Hostel", "Parking", 90),
    ("Parking", "Medical Centre", 70),
]

# Two extra roads that are clearly visible on the campus map:
#   * the northern boundary road  (Administration <-> Library)
#   * the southern lake-side road (Laboratory <-> Medical Centre)
# They make the graph 2-edge-connected (no single blocked road can isolate
# a building) and they create a case where BFS and Dijkstra DISAGREE:
#   Academic Block -> Medical Centre
#       BFS      : AC -> LAB -> M              (2 edges, 480 m)
#       Dijkstra : AC -> LAB -> H -> P -> M    (4 edges, 440 m)
# Set INCLUDE_EXTRA_ROADS = False to use only the 9 core roads.
EXTRA_ROADS = [
    ("Administration Building", "Library", 180),
    ("Laboratory", "Medical Centre", 400),
]

INCLUDE_EXTRA_ROADS = True


def get_roads():
    """Return the list of (u, v, weight) edges currently configured."""
    roads = list(CORE_ROADS)
    if INCLUDE_EXTRA_ROADS:
        roads.extend(EXTRA_ROADS)
    return roads


# ---------------------------------------------------------------------------
# 3. MAP COORDINATES of every building (pixels on campus_map.png)
# ---------------------------------------------------------------------------
MAP_WIDTH = 1024
MAP_HEIGHT = 572

NODE_POSITIONS = {
    "Administration Building": (183, 150),   # upper-left
    "Library": (510, 148),                    # upper-centre
    "Hostel": (850, 160),                     # upper-right
    "Academic Block": (365, 300),             # centre-left
    "Cafeteria": (615, 300),                  # centre-right
    "Parking": (850, 330),                    # right-middle
    "Laboratory": (170, 430),                 # lower-left
    "Medical Centre": (855, 450),             # lower-right
}

# ---------------------------------------------------------------------------
# 4. ROAD POLY-LINES – intermediate points that follow the painted roads.
#    Key = (u, v) exactly as in the edge list; the UI reverses the list
#    automatically when the edge is travelled from v to u.
#    The building positions are added at both ends automatically.
# ---------------------------------------------------------------------------
ROAD_WAYPOINTS = {
    ("Academic Block", "Library"): [(365, 230), (510, 230)],
    ("Academic Block", "Laboratory"): [(193, 300), (200, 345), (240, 390)],
    ("Academic Block", "Administration Building"): [(365, 230), (183, 230)],
    ("Library", "Cafeteria"): [(510, 230), (615, 230)],
    ("Laboratory", "Cafeteria"): [(262, 445), (306, 447), (345, 406), (615, 402)],
    ("Laboratory", "Hostel"): [(262, 445), (306, 447), (345, 406), (706, 402),
                               (706, 240), (850, 240)],
    ("Cafeteria", "Hostel"): [(706, 300), (706, 240), (850, 240)],
    ("Hostel", "Parking"): [(850, 240)],
    ("Parking", "Medical Centre"): [(850, 402)],
    ("Administration Building", "Library"): [(183, 65), (510, 65)],
    ("Laboratory", "Medical Centre"): [(262, 445), (306, 447), (316, 470), (316, 555),
                                       (706, 555), (706, 450)],
}
