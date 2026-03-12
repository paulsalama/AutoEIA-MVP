"""
Shadow Context Builder
======================
Fetches all surrounding buildings from the NYC Building Footprints SODA API
and extrudes them to LOD1 flat-top boxes in OBJ format.

This establishes the No-Action context for CEQR Chapter 8 incremental shadow
analysis: once you have the surrounding massing, Module C (shadow-incremental)
can isolate exactly how much NEW shadow the project building casts.

Coordinate system for the OBJ output
--------------------------------------
  - Origin : project centroid (lat/lon projected to local metres)
  - X      : East
  - Y      : North
  - Z      : Up
  - Units  : metres

This matches the convention used by shadow-tier-3-obj and shadow-incremental.
"""

import math
import json
import urllib.request
import urllib.parse

# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _to_local_m(lon, lat, origin_lon, origin_lat):
    """WGS84 lon/lat -> (x_east_m, y_north_m) relative to origin."""
    R = 6_371_000.0
    lat_r = math.radians(lat)
    olat_r = math.radians(origin_lat)
    x = math.radians(lon - origin_lon) * R * math.cos(olat_r)
    y = math.radians(lat - origin_lat) * R
    return x, y


def _centroid_of_geojson(geojson):
    """Return (lat, lon) centroid of the first feature in a GeoJSON object."""
    features = geojson.get("features", [])
    if not features:
        raise ValueError("building_geojson has no features")
    geom = features[0].get("geometry", {})
    gtype = geom.get("type", "")
    coords = geom.get("coordinates", [])

    def _flatten(ring):
        return ring

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
    """Return a list of outer coordinate rings from Polygon / MultiPolygon."""
    gtype = geometry.get("type", "")
    coords = geometry.get("coordinates", [])
    if gtype == "Polygon":
        return [coords[0]]
    elif gtype == "MultiPolygon":
        return [poly[0] for poly in coords]
    return []


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

FOOTPRINTS_URL = "https://data.cityofnewyork.us/resource/5zhs-2jue.geojson"
PAGE_LIMIT = 5000


def _fetch_footprints(lat, lon, radius_ft):
    """
    Query NYC Building Footprints SODA API for buildings within radius_ft of
    (lat, lon).  Returns a GeoJSON FeatureCollection dict.

    Dataset: 5zhs-2jue (Building Footprints, NYC Open Data)
    Fields:  height_roof, construction_year, bin, base_bbl, ground_elevation
    """
    radius_m = radius_ft * 0.3048
    where = f"within_circle(the_geom,{lat},{lon},{radius_m:.1f})"
    # Must URL-encode manually — $limit as a bare shell arg gets swallowed
    params = urllib.parse.urlencode({
        "$where": where,
        "$limit": PAGE_LIMIT,
        "$select": "the_geom,bin,base_bbl,height_roof,ground_elevation,construction_year,last_edited_date",
    })
    url = f"{FOOTPRINTS_URL}?{params}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data


# ---------------------------------------------------------------------------
# OBJ extrusion
# ---------------------------------------------------------------------------

def _extrude_to_obj(buildings, origin_lat, origin_lon):
    """
    Generate an OBJ string for all buildings.

    buildings : list of dicts with keys:
        ring      - list of [lon, lat] pairs (outer ring)
        height_m  - building height in metres
        bin       - NYC BIN (used as group name)

    Returns OBJ text (str).
    """
    lines = [
        "# Shadow Context Builder — LOD1 massing",
        "# Units: metres  |  X=East  Y=North  Z=Up",
        "# Origin: project centroid",
        "",
    ]

    v_offset = 0  # global vertex counter

    for bldg in buildings:
        ring = bldg["ring"]
        h = bldg["height_m"]
        bid = bldg.get("bin", "unknown")

        # Project ring to local metres
        pts = [_to_local_m(c[0], c[1], origin_lon, origin_lat) for c in ring]

        # Close ring if needed
        if pts and pts[0] != pts[-1]:
            pts.append(pts[0])

        # De-duplicate consecutive identical points
        deduped = [pts[0]]
        for p in pts[1:]:
            if p != deduped[-1]:
                deduped.append(p)
        pts = deduped

        # Need at least 3 unique vertices (triangle minimum)
        if len(pts) < 3:
            continue

        n = len(pts)
        lines.append(f"g bin_{bid}")

        # Bottom vertices (z=0)
        for x, y in pts:
            lines.append(f"v {x:.4f} {y:.4f} 0.0000")
        # Top vertices (z=h)
        for x, y in pts:
            lines.append(f"v {x:.4f} {y:.4f} {h:.4f}")

        # Bottom face (reverse winding for downward normal)
        bottom = " ".join(str(v_offset + i + 1) for i in range(n - 1, -1, -1))
        lines.append(f"f {bottom}")

        # Top face
        top = " ".join(str(v_offset + n + i + 1) for i in range(n))
        lines.append(f"f {top}")

        # Wall quads
        for i in range(n - 1):
            b0 = v_offset + i + 1
            b1 = v_offset + i + 2
            t0 = v_offset + n + i + 1
            t1 = v_offset + n + i + 2
            lines.append(f"f {b0} {b1} {t1} {t0}")

        lines.append("")
        v_offset += 2 * n

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Visualization
# ---------------------------------------------------------------------------

def _build_map(buildings_geojson, lat, lon, radius_ft):
    """
    Return Folium map HTML string.
    Buildings colored by height: blue <100 ft, amber 100-300 ft, red >300 ft.
    """
    try:
        import folium
    except ImportError:
        return "<p>folium not installed — no visualization</p>"

    m = folium.Map(location=[lat, lon], zoom_start=15, tiles="CartoDB positron")

    # Study area circle
    folium.Circle(
        location=[lat, lon],
        radius=radius_ft * 0.3048,
        color="#6366f1",
        fill=False,
        weight=2,
        tooltip="Study area boundary",
    ).add_to(m)

    # Project marker
    folium.Marker(
        location=[lat, lon],
        tooltip="Project site",
        icon=folium.Icon(color="red", icon="star"),
    ).add_to(m)

    # Buildings
    for feat in buildings_geojson.get("features", []):
        props = feat.get("properties", {})
        height_ft = props.get("height_ft", 0) or 0
        if height_ft < 100:
            color = "#3b82f6"
        elif height_ft < 300:
            color = "#f59e0b"
        else:
            color = "#ef4444"

        tooltip = (
            f"BIN: {props.get('bin', 'N/A')} | "
            f"Height: {height_ft:.0f} ft | "
            f"Built: {props.get('cnstrct_yr', 'N/A')}"
        )

        try:
            folium.GeoJson(
                feat,
                style_function=lambda _f, c=color: {
                    "fillColor": c,
                    "color": c,
                    "weight": 1,
                    "fillOpacity": 0.5,
                },
                tooltip=tooltip,
            ).add_to(m)
        except Exception:
            pass

    # Legend
    legend_html = """
    <div style="position:fixed;bottom:30px;left:30px;z-index:9999;
                background:white;padding:10px;border-radius:6px;
                border:1px solid #ccc;font-size:12px;line-height:1.8">
      <b>Height</b><br>
      <span style="color:#3b82f6">&#9632;</span> &lt; 100 ft<br>
      <span style="color:#f59e0b">&#9632;</span> 100–300 ft<br>
      <span style="color:#ef4444">&#9632;</span> &gt; 300 ft<br>
      <span style="color:red">&#9733;</span> Project site
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))

    return m._repr_html_()


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

DEFAULT_HEIGHT_FT = 35.0   # fallback when heightroof is missing
CEQR_BUFFER_FACTOR = 4.3   # longest-shadow multiplier (CEQR Ch. 8)
RADIUS_BUFFER_FT = 200.0   # extra buffer beyond longest shadow


def execute(inputs):
    # ------------------------------------------------------------------
    # 1. Resolve project location
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
    elif inputs.get("building_geojson"):
        lat, lon = _centroid_of_geojson(inputs["building_geojson"])
    else:
        raise ValueError(
            "Either project_location or building_geojson must be provided."
        )

    # ------------------------------------------------------------------
    # 2. Resolve study area radius
    # ------------------------------------------------------------------
    radius_ft = inputs.get("study_area_radius_ft")
    if radius_ft:
        radius_ft = float(radius_ft)
    else:
        height_ft = inputs.get("building_height_ft")
        if height_ft:
            radius_ft = float(height_ft) * CEQR_BUFFER_FACTOR + RADIUS_BUFFER_FT
        else:
            radius_ft = 1500.0  # conservative default

    # ------------------------------------------------------------------
    # 3. Fetch surrounding buildings
    # ------------------------------------------------------------------
    raw_fc = _fetch_footprints(lat, lon, radius_ft)
    features = raw_fc.get("features", [])

    # ------------------------------------------------------------------
    # 4. Filter project site buildings
    # ------------------------------------------------------------------
    exclude_bins = set(str(b) for b in (inputs.get("project_site_bins") or []))
    exclude_bbls = set(str(b) for b in (inputs.get("project_site_bbls") or []))

    filtered = []
    for feat in features:
        props = feat.get("properties", {}) or {}
        if str(props.get("bin", "")) in exclude_bins:
            continue
        if str(props.get("base_bbl", "")) in exclude_bbls:
            continue
        filtered.append(feat)

    # ------------------------------------------------------------------
    # 5. Build inventory + flag data gaps
    # ------------------------------------------------------------------
    buildings_for_obj = []   # dicts for OBJ extrusion
    geojson_features = []    # for context_geojson output
    inventory = []
    missing_height = []
    post_2014 = []

    for feat in filtered:
        props = feat.get("properties", {}) or {}
        geom = feat.get("geometry", {}) or {}

        # Height resolution (field: height_roof in dataset 5zhs-2jue)
        raw_h = props.get("height_roof")
        if raw_h is not None:
            try:
                height_ft = float(raw_h)
                height_source = "height_roof"
            except (ValueError, TypeError):
                height_ft = DEFAULT_HEIGHT_FT
                height_source = "default"
        else:
            height_ft = DEFAULT_HEIGHT_FT
            height_source = "default"
            missing_height.append(str(props.get("bin", "?")))

        height_m = height_ft * 0.3048

        # Construction year (field: construction_year)
        cnstrct_yr = props.get("construction_year")
        try:
            cnstrct_yr = int(cnstrct_yr) if cnstrct_yr else None
        except (ValueError, TypeError):
            cnstrct_yr = None

        if cnstrct_yr and cnstrct_yr > 2014:
            post_2014.append(str(props.get("bin", "?")))

        bin_val = str(props.get("bin", ""))
        bbl_val = str(props.get("base_bbl", ""))

        # Extract outer rings
        rings = _outer_rings(geom)
        for ring in rings:
            if len(ring) >= 3:
                buildings_for_obj.append({
                    "ring": ring,
                    "height_m": height_m,
                    "bin": bin_val,
                })

        # GeoJSON feature for output
        geojson_features.append({
            "type": "Feature",
            "geometry": geom,
            "properties": {
                "bin": bin_val,
                "bbl": bbl_val,
                "height_ft": round(height_ft, 1),
                "height_m": round(height_m, 2),
                "height_source": height_source,
                "cnstrct_yr": cnstrct_yr,
                "last_edited_date": str(props.get("last_edited_date", "")),
            },
        })

        inventory.append({
            "bin": bin_val,
            "bbl": bbl_val,
            "height_ft": round(height_ft, 1),
            "height_source": height_source,
            "cnstrct_yr": cnstrct_yr,
        })

    # ------------------------------------------------------------------
    # 6. Generate OBJ massing
    # ------------------------------------------------------------------
    obj_text = _extrude_to_obj(buildings_for_obj, lat, lon)

    # ------------------------------------------------------------------
    # 7. Build visualization
    # ------------------------------------------------------------------
    context_fc = {"type": "FeatureCollection", "features": geojson_features}
    viz_html = _build_map(context_fc, lat, lon, radius_ft)

    # ------------------------------------------------------------------
    # 8. Data gap report
    # ------------------------------------------------------------------
    data_gap_report = {
        "total_buildings": len(filtered),
        "missing_height_count": len(missing_height),
        "missing_height_bins": missing_height[:20],  # cap list for readability
        "missing_height_note": (
            f"{len(missing_height)} buildings had no heightroof value and were "
            f"assigned a default of {DEFAULT_HEIGHT_FT} ft."
        ) if missing_height else "All buildings have height data.",
        "post_2014_count": len(post_2014),
        "post_2014_note": (
            f"{len(post_2014)} buildings constructed after 2014 may lack LOD2 "
            "data in the city model; LOD1 extrusion used for all."
        ) if post_2014 else "No post-2014 buildings flagged.",
        "data_freshness": "NYC Building Footprints updated quarterly via NYC Open Data (dataset 5zhs-2jue).",
    }

    # ------------------------------------------------------------------
    # 9. Return outputs
    # ------------------------------------------------------------------
    return {
        "context_mesh_obj": obj_text,
        "context_geojson": context_fc,
        "building_inventory": inventory,
        "data_gap_report": data_gap_report,
        "building_count": len(filtered),
        "study_area_radius_ft": radius_ft,
        "project_location": [lat, lon],
        "visualization": viz_html,
    }


# ---------------------------------------------------------------------------
# Standalone test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("Testing Shadow Context Builder...")
    result = execute({
        "building_height_ft": 400,
        "study_area_radius_ft": 2000,
        "project_location": [40.7536, -73.9832],
    })
    print(f"Buildings fetched: {result['building_count']}")
    print(f"Radius used: {result['study_area_radius_ft']} ft")
    print(f"OBJ size: {len(result['context_mesh_obj']):,} chars")
    print(f"Data gap report: {result['data_gap_report']}")
    print("Done.")
