"""
Shadow Pipeline Builder
=======================
Assembles the No-Action and With-Action 3D scenes for CEQR Chapter 8
incremental shadow analysis.

What it does
------------
1. Extrudes the project building footprint into an OBJ mesh (same local
   coordinate system as Shadow Context Builder: origin = project centroid,
   X=East, Y=North, Z=Up, metres).
2. Accepts the surrounding context mesh from Shadow Context Builder
   (context_mesh_obj) and passes it through as no_action_mesh_obj.
3. Combines context + project OBJ into with_action_mesh_obj so Module C
   (shadow-incremental) can project shadows for both scenes and diff them.
4. Resolves CEQR-compliant analysis dates and time windows.

Coordinate system
-----------------
All OBJ outputs share the same origin (project centroid in local metres),
so they can be concatenated or used separately by downstream modules.
"""

import math
import json
from datetime import date

# ---------------------------------------------------------------------------
# CEQR analysis parameters
# ---------------------------------------------------------------------------

CEQR_DATES = {
    "NYC":     ["12-21", "03-21", "05-06", "06-21"],
    "generic": ["12-21", "03-21", "06-21"],
}

# Analysis window: 1.5 h after sunrise to 1.5 h before sunset (EST, no DST)
# Shadow-incremental will compute per-date sunrise/sunset; we just pass the rule.
ANALYSIS_WINDOW = {"start_offset_h": 1.5, "end_offset_h": -1.5, "tz": "EST"}


def _ceqr_dates(jurisdiction, year):
    """Return ISO date strings for the CEQR representative days."""
    stems = CEQR_DATES.get(jurisdiction, CEQR_DATES["NYC"])
    return [f"{year}-{s}" for s in stems]


# ---------------------------------------------------------------------------
# Geometry helpers (duplicated from shadow_context_builder to keep modules
# self-contained — no cross-module imports in this SDK)
# ---------------------------------------------------------------------------

def _to_local_m(lon, lat, origin_lon, origin_lat):
    R = 6_371_000.0
    x = math.radians(lon - origin_lon) * R * math.cos(math.radians(origin_lat))
    y = math.radians(lat - origin_lat) * R
    return x, y


def _centroid_of_geojson(geojson):
    features = geojson.get("features", [])
    if not features:
        raise ValueError("building_geojson has no features")
    geom = features[0].get("geometry", {})
    gtype = geom.get("type", "")
    coords = geom.get("coordinates", [])
    if gtype == "Polygon":
        ring = coords[0]
    elif gtype == "MultiPolygon":
        ring = coords[0][0]
    else:
        raise ValueError(f"Unsupported geometry type: {gtype}")
    lons = [c[0] for c in ring]
    lats = [c[1] for c in ring]
    return sum(lats) / len(lats), sum(lons) / len(lons)


def _outer_rings(geometry):
    gtype = geometry.get("type", "")
    coords = geometry.get("coordinates", [])
    if gtype == "Polygon":
        return [coords[0]]
    elif gtype == "MultiPolygon":
        return [poly[0] for poly in coords]
    return []


# ---------------------------------------------------------------------------
# OBJ extrusion (project building)
# ---------------------------------------------------------------------------

def _extrude_project_to_obj(geojson, height_m, origin_lat, origin_lon):
    """
    Extrude all footprint rings in geojson to a flat-top LOD1 OBJ mesh.
    Returns OBJ text string.
    """
    lines = [
        "# Shadow Pipeline Builder — project building mesh",
        "# Units: metres  |  X=East  Y=North  Z=Up",
        "# Origin: project centroid",
        "",
        "g project_building",
    ]
    v_offset = 0

    for feat in geojson.get("features", []):
        geom = feat.get("geometry", {})
        rings = _outer_rings(geom)
        for ring in rings:
            pts = [_to_local_m(c[0], c[1], origin_lon, origin_lat) for c in ring]
            # Close + de-dup
            if pts and pts[0] != pts[-1]:
                pts.append(pts[0])
            deduped = [pts[0]]
            for p in pts[1:]:
                if p != deduped[-1]:
                    deduped.append(p)
            pts = deduped
            if len(pts) < 3:
                continue

            n = len(pts)
            for x, y in pts:
                lines.append(f"v {x:.4f} {y:.4f} 0.0000")
            for x, y in pts:
                lines.append(f"v {x:.4f} {y:.4f} {height_m:.4f}")

            # Bottom face
            bottom = " ".join(str(v_offset + i + 1) for i in range(n - 1, -1, -1))
            lines.append(f"f {bottom}")
            # Top face
            top = " ".join(str(v_offset + n + i + 1) for i in range(n))
            lines.append(f"f {top}")
            # Walls
            for i in range(n - 1):
                b0, b1 = v_offset + i + 1, v_offset + i + 2
                t0, t1 = v_offset + n + i + 1, v_offset + n + i + 2
                lines.append(f"f {b0} {b1} {t1} {t0}")

            lines.append("")
            v_offset += 2 * n

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# OBJ combining
# ---------------------------------------------------------------------------

def _combine_objs(obj_a, obj_b):
    """
    Concatenate two OBJ strings, re-indexing obj_b vertices so they don't
    clash with obj_a.  Returns combined OBJ text.
    """
    if not obj_a:
        return obj_b or ""
    if not obj_b:
        return obj_a or ""

    # Count vertices in obj_a
    v_count = sum(1 for line in obj_a.splitlines() if line.startswith("v "))

    lines_b = []
    for line in obj_b.splitlines():
        parts = line.strip().split()
        if not parts:
            lines_b.append(line)
            continue
        if parts[0] == "f":
            # Re-index face vertices
            new_parts = ["f"]
            for token in parts[1:]:
                # Handle v/vt/vn slash notation
                sub = token.split("/")
                sub[0] = str(int(sub[0]) + v_count)
                new_parts.append("/".join(sub))
            lines_b.append(" ".join(new_parts))
        else:
            lines_b.append(line)

    return obj_a.rstrip() + "\n\n# --- project building (appended) ---\n" + "\n".join(lines_b)


# ---------------------------------------------------------------------------
# Visualization
# ---------------------------------------------------------------------------

def _build_map(geojson, lat, lon, height_ft):
    try:
        import folium
    except ImportError:
        return "<p>folium not installed — no visualization</p>"

    m = folium.Map(location=[lat, lon], zoom_start=16, tiles="CartoDB positron")

    folium.Marker(
        location=[lat, lon],
        tooltip=f"Project site — {height_ft:.0f} ft",
        icon=folium.Icon(color="red", icon="star"),
    ).add_to(m)

    folium.GeoJson(
        geojson,
        style_function=lambda _f: {
            "fillColor": "#ef4444",
            "color": "#b91c1c",
            "weight": 2,
            "fillOpacity": 0.5,
        },
        tooltip=f"Project building: {height_ft:.0f} ft",
    ).add_to(m)

    legend_html = f"""
    <div style="position:fixed;bottom:30px;left:30px;z-index:9999;
                background:white;padding:10px;border-radius:6px;
                border:1px solid #ccc;font-size:12px">
      <b>Project Building</b><br>
      Height: {height_ft:.0f} ft ({height_ft * 0.3048:.1f} m)<br>
      <span style="color:#ef4444">&#9632;</span> Project footprint
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))

    return m._repr_html_()


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def execute(inputs):
    # ------------------------------------------------------------------
    # 1. Resolve project building source
    # ------------------------------------------------------------------
    building_obj = inputs.get("building_obj")  # optional: pre-built OBJ
    building_geojson = inputs.get("building_geojson")

    if not building_obj and not building_geojson:
        raise ValueError("Either building_obj or building_geojson is required.")

    building_height_ft = inputs.get("building_height_ft")
    if not building_obj and building_height_ft is None:
        raise ValueError("building_height_ft is required when building_obj is not provided.")
    if building_height_ft is not None:
        building_height_ft = float(building_height_ft)
    building_height_m = building_height_ft * 0.3048 if building_height_ft is not None else None

    # ------------------------------------------------------------------
    # 2. Resolve project location
    # ------------------------------------------------------------------
    project_location = inputs.get("project_location")
    if project_location:
        if isinstance(project_location, (list, tuple)) and len(project_location) >= 2:
            lat, lon = float(project_location[0]), float(project_location[1])
        elif isinstance(project_location, dict):
            lat = float(project_location.get("lat", project_location.get("latitude", 0)))
            lon = float(project_location.get("lon", project_location.get("longitude", 0)))
        else:
            raise ValueError("project_location must be [lat, lon] or {lat, lon}")
    elif building_geojson:
        lat, lon = _centroid_of_geojson(building_geojson)
    else:
        raise ValueError("project_location is required when building_geojson is not provided.")

    # ------------------------------------------------------------------
    # 3. Resolve analysis parameters
    # ------------------------------------------------------------------
    jurisdiction = inputs.get("jurisdiction", "NYC")
    analysis_year = date.today().year
    analysis_dates = inputs.get("analysis_dates") or _ceqr_dates(jurisdiction, analysis_year)

    # ------------------------------------------------------------------
    # 4. Project building mesh — use supplied OBJ or extrude from footprint
    # ------------------------------------------------------------------
    if building_obj:
        project_mesh_obj = building_obj
    else:
        project_mesh_obj = _extrude_project_to_obj(
            building_geojson, building_height_m, lat, lon
        )

    # ------------------------------------------------------------------
    # 5. Assemble No-Action and With-Action scenes
    # ------------------------------------------------------------------
    context_mesh_obj = inputs.get("context_mesh_obj") or ""
    no_action_mesh_obj = context_mesh_obj
    with_action_mesh_obj = _combine_objs(context_mesh_obj, project_mesh_obj)

    # ------------------------------------------------------------------
    # 6. Visualization
    # ------------------------------------------------------------------
    viz_html = _build_map(building_geojson, lat, lon, building_height_ft or 0) if building_geojson else "<p>No footprint provided — visualization unavailable</p>"

    # ------------------------------------------------------------------
    # 7. Return outputs
    # ------------------------------------------------------------------
    return {
        "project_mesh_obj": project_mesh_obj,
        "no_action_mesh_obj": no_action_mesh_obj,
        "with_action_mesh_obj": with_action_mesh_obj,
        "project_location": [lat, lon],
        "building_height_ft": building_height_ft,
        "study_area_radius_ft": inputs.get("study_area_radius_ft"),
        "analysis_dates": analysis_dates,
        "analysis_year": analysis_year,
        "visualization": viz_html,
    }


# ---------------------------------------------------------------------------
# Standalone test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("Testing Shadow Pipeline Builder...")

    test_footprint = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [-73.9840, 40.7530],
                        [-73.9825, 40.7530],
                        [-73.9825, 40.7542],
                        [-73.9840, 40.7542],
                        [-73.9840, 40.7530],
                    ]],
                },
                "properties": {},
            }
        ],
    }

    result = execute({
        "building_geojson": test_footprint,
        "building_height_ft": 400,
        "project_location": [40.7536, -73.9832],
    })

    print(f"Analysis dates:       {result['analysis_dates']}")
    print(f"Analysis year:        {result['analysis_year']}")
    print(f"Project OBJ size:     {len(result['project_mesh_obj']):,} chars")
    print(f"No-action OBJ size:   {len(result['no_action_mesh_obj']):,} chars (empty — no context passed)")
    print(f"With-action OBJ size: {len(result['with_action_mesh_obj']):,} chars")
    print(f"Project location:     {result['project_location']}")
    print("Done.")
