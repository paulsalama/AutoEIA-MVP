"""
Shadow Incremental Calculator
==============================
CEQR Technical Manual Chapter 8, Sections 314-325.

This module computes INCREMENTAL shadow: the additional shadow cast by the
proposed project building that does not already exist in the No-Action condition.

  Incremental shadow = With-Action shadow − No-Action shadow

Both OBJ meshes share the same local coordinate system (origin = project
centroid, X=East, Y=North, Z=Up, metres), produced by Shadow Context Builder
and Shadow Pipeline Builder.

Pipeline
--------
    Shadow Context Builder  →  shadow_pipeline_builder  →  shadow_incremental
    (Module A)                  (Module B)                  (Module C — this)

Algorithm
---------
1. Parse both OBJ meshes (vertices in local metres, faces).
2. Translate vertices to UTM by offsetting by the UTM projection of the
   project centroid — valid for study areas ≤ ~5 km radius.
3. For each CEQR analysis datetime:
     a. Compute solar altitude + azimuth (pysolar).
     b. Project per-face shadows from No-Action mesh → union polygon.
     c. Project per-face shadows from With-Action mesh → union polygon.
     d. Incremental = With-Action.difference(No-Action).
     e. Record area, convert to WGS84.
4. Intersect incremental shadow polygons with sensitive sites GeoDataFrame.
5. Aggregate by site, generate report and Folium visualization.
"""

import json
import math
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path

warnings.filterwarnings("ignore", message="I don't know about leap seconds")

EST = timezone(timedelta(hours=-5))

# CEQR analysis time interval (minutes)
DEFAULT_INTERVAL_MIN = 60

# Minimum solar altitude to compute shadows (degrees)
MIN_SOLAR_ALT = 2.0

# CEQR time window offset from sunrise/sunset (hours)
WINDOW_OFFSET_H = 1.5


# ---------------------------------------------------------------------------
# OBJ parsing
# ---------------------------------------------------------------------------

def _parse_obj(obj_text):
    """
    Parse OBJ text into vertices (local metres) and faces (0-indexed).
    Returns (vertices, faces).
    Comments, group names, normals, and texture coords are ignored.
    """
    vertices = []
    faces = []
    for line in obj_text.splitlines():
        parts = line.strip().split()
        if not parts:
            continue
        if parts[0] == "v":
            try:
                x, y, z = float(parts[1]), float(parts[2]), float(parts[3])
                vertices.append((x, y, z))
            except (IndexError, ValueError):
                continue
        elif parts[0] == "f":
            indices = []
            for token in parts[1:]:
                try:
                    idx = int(token.split("/")[0]) - 1  # OBJ is 1-indexed
                    indices.append(idx)
                except ValueError:
                    continue
            if len(indices) >= 3:
                faces.append(indices)
    return vertices, faces


# ---------------------------------------------------------------------------
# Coordinate conversion
# ---------------------------------------------------------------------------

def _get_utm_transformers(lon, lat):
    from pyproj import Transformer
    zone = int((lon + 180) / 6) + 1
    epsg = 32600 + zone if lat >= 0 else 32700 + zone
    wgs_to_utm = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
    utm_to_wgs = Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True)
    return wgs_to_utm, utm_to_wgs


def _local_to_utm(vertices_local, cx_utm, cy_utm):
    """
    Translate local-metre vertices (X=East, Y=North from project centroid)
    to UTM by offsetting by the UTM projection of the project centroid.
    Z is unchanged (metres above ground).
    """
    return [(cx_utm + x, cy_utm + y, z) for x, y, z in vertices_local]


def _poly_to_wgs(polygon, utm_to_wgs):
    """Convert a Shapely polygon from UTM to WGS84."""
    from shapely.geometry import Polygon, MultiPolygon
    if polygon is None or polygon.is_empty:
        return None

    def _ring_to_wgs(ring):
        return [utm_to_wgs.transform(x, y) for x, y in ring]

    if polygon.geom_type == "Polygon":
        ext = _ring_to_wgs(list(polygon.exterior.coords))
        holes = [_ring_to_wgs(list(i.coords)) for i in polygon.interiors]
        return Polygon(ext, holes)
    elif polygon.geom_type == "MultiPolygon":
        parts = []
        for geom in polygon.geoms:
            ext = _ring_to_wgs(list(geom.exterior.coords))
            holes = [_ring_to_wgs(list(i.coords)) for i in geom.interiors]
            parts.append(Polygon(ext, holes))
        return MultiPolygon(parts)
    return None


# ---------------------------------------------------------------------------
# Shadow projection
# ---------------------------------------------------------------------------

def _project_shadow(vertices_utm, faces, solar_altitude_deg, solar_azimuth_deg):
    """
    Per-face shadow projection. Returns a Shapely polygon (UTM) or None.

    Convention (matches shadow_tier3_obj.py):
      Shadow direction = sun azimuth + 180°  (shadow falls opposite to sun)
      Shadow tip of vertex (x, y, z):
        tip_x = x + z / tan(alt) * sin(shadow_az)
        tip_y = y + z / tan(alt) * cos(shadow_az)
    """
    from shapely.geometry import MultiPoint
    from shapely.ops import unary_union

    if solar_altitude_deg <= MIN_SOLAR_ALT:
        return None

    tan_alt = math.tan(math.radians(solar_altitude_deg))
    shadow_az_rad = math.radians((solar_azimuth_deg + 180.0) % 360.0)
    sin_az = math.sin(shadow_az_rad)
    cos_az = math.cos(shadow_az_rad)

    def shadow_tip(x, y, z):
        if z <= 0.1:
            return (x, y)
        return (x + z / tan_alt * sin_az, y + z / tan_alt * cos_az)

    shadow_polys = []
    for face in faces:
        verts = [vertices_utm[i] for i in face if 0 <= i < len(vertices_utm)]
        if len(verts) < 3:
            continue
        # Skip faces entirely at ground level — they cast no shadow
        if max(v[2] for v in verts) <= 0.1:
            continue
        ground_pts = [(v[0], v[1]) for v in verts]
        tip_pts = [shadow_tip(v[0], v[1], v[2]) for v in verts]
        all_pts = ground_pts + tip_pts
        try:
            hull = MultiPoint(all_pts).convex_hull
            if hull.is_valid and not hull.is_empty and hull.area > 0:
                shadow_polys.append(hull)
        except Exception:
            continue

    if not shadow_polys:
        return None
    # Cascade union in chunks to avoid O(n²) Shapely behaviour on large sets
    while len(shadow_polys) > 1:
        next_level = []
        for i in range(0, len(shadow_polys), 64):
            chunk = shadow_polys[i:i + 64]
            merged = unary_union(chunk)
            next_level.append(merged)
        shadow_polys = next_level
    result = shadow_polys[0]
    return result if result.is_valid else None


# ---------------------------------------------------------------------------
# Solar time window
# ---------------------------------------------------------------------------

def _find_crossing(lat, lon, year, month, day, search_start_h, search_end_h, rising):
    """
    Binary-search for sunrise (rising=True) or sunset (rising=False)
    between search_start_h and search_end_h (hours, EST).
    Returns a datetime or None.  ~10 iterations vs 216 linear scans.
    """
    from pysolar.solar import get_altitude
    lo = datetime(year, month, day, search_start_h, 0, 0, tzinfo=EST)
    hi = datetime(year, month, day, search_end_h, 0, 0, tzinfo=EST)
    for _ in range(10):
        mid = lo + (hi - lo) / 2
        alt = get_altitude(lat, lon, mid)
        if (alt > 0) == rising:
            hi = mid
        else:
            lo = mid
    result = lo + (hi - lo) / 2
    # Verify there actually is a crossing in this range
    alt_lo = get_altitude(lat, lon, lo)
    alt_hi = get_altitude(lat, lon, hi)
    if (alt_lo > 0) == (alt_hi > 0):
        return None  # no crossing found
    return result


def _analysis_times(lat, lon, year, month, day, interval_min):
    """
    Return list of EST datetimes in the CEQR analysis window for this date:
    sunrise + 1.5 h  to  sunset - 1.5 h, at `interval_min` intervals.
    Uses binary search for sunrise/sunset (~20 pysolar calls vs 216).
    """
    sunrise_dt = _find_crossing(lat, lon, year, month, day, 4, 10, rising=True)
    sunset_dt  = _find_crossing(lat, lon, year, month, day, 15, 21, rising=False)

    if not sunrise_dt or not sunset_dt:
        return []

    window_start = sunrise_dt + timedelta(hours=WINDOW_OFFSET_H)
    window_end = sunset_dt - timedelta(hours=WINDOW_OFFSET_H)

    if window_start >= window_end:
        return []

    times = []
    t = window_start
    while t <= window_end:
        times.append(t)
        t += timedelta(minutes=interval_min)
    return times


# ---------------------------------------------------------------------------
# Sensitive sites loading
# ---------------------------------------------------------------------------

def _load_sensitive_sites(sensitive_sites_input):
    import geopandas as gpd

    if sensitive_sites_input:
        if isinstance(sensitive_sites_input, str):
            sensitive_sites_input = json.loads(sensitive_sites_input)
        sites_gdf = gpd.GeoDataFrame.from_features(sensitive_sites_input["features"])
        if sites_gdf.crs is None:
            sites_gdf = sites_gdf.set_crs(epsg=4326)
        return sites_gdf

    default_path = (
        Path(__file__).parent.parent.parent
        / "datasets"
        / "nyc_dpr_parks_properties.geojson"
    )
    if default_path.exists():
        sites_gdf = gpd.read_file(str(default_path))
        for col in sites_gdf.select_dtypes(include=["datetime64"]).columns:
            sites_gdf[col] = sites_gdf[col].astype(str)
        return sites_gdf

    return None


def _site_name(row, idx):
    return row.get("signname") or row.get("propname") or row.get("name") or f"Site {idx}"


# ---------------------------------------------------------------------------
# Visualization
# ---------------------------------------------------------------------------

def _build_map(incremental_features, affected_sites_gdf, unaffected_sites_gdf, lat, lon):
    try:
        import folium
        from shapely.geometry import mapping
    except ImportError:
        return "<p>folium/shapely not installed</p>"

    m = folium.Map(location=[lat, lon], zoom_start=15, tiles="CartoDB positron")

    palette = ["#ef4444", "#f97316", "#eab308", "#22c55e",
               "#06b6d4", "#6366f1", "#a855f7", "#ec4899"]
    unique_dates = sorted(set(f["properties"]["date"] for f in incremental_features))
    date_colors = {d: palette[i % len(palette)] for i, d in enumerate(unique_dates)}

    for d in unique_dates:
        color = date_colors[d]
        day_feats = [f for f in incremental_features if f["properties"]["date"] == d]
        if not day_feats:
            continue
        folium.GeoJson(
            {"type": "FeatureCollection", "features": day_feats},
            name=f"Incremental shadow — {d}",
            style_function=lambda _f, c=color: {
                "fillColor": c, "color": c, "weight": 0.5, "fillOpacity": 0.25,
            },
            tooltip=folium.GeoJsonTooltip(
                fields=["time_est", "solar_altitude_deg", "incremental_area_sqft"],
                aliases=["Time (EST):", "Solar altitude (°):", "New shadow area (sq ft):"],
            ),
        ).add_to(m)

    if unaffected_sites_gdf is not None and not unaffected_sites_gdf.empty:
        folium.GeoJson(
            json.loads(unaffected_sites_gdf.to_json()),
            name="Sensitive sites — no incremental shadow",
            style_function=lambda _f: {
                "fillColor": "#a78bfa", "color": "#7c3aed", "weight": 1, "fillOpacity": 0.35,
            },
        ).add_to(m)

    if affected_sites_gdf is not None and not affected_sites_gdf.empty:
        folium.GeoJson(
            json.loads(affected_sites_gdf.to_json()),
            name="Sensitive sites — INCREMENTAL shadow impact",
            style_function=lambda _f: {
                "fillColor": "#f97316", "color": "#c2410c", "weight": 2, "fillOpacity": 0.75,
            },
        ).add_to(m)

    folium.Marker(
        location=[lat, lon],
        tooltip="Project site",
        icon=folium.Icon(color="red", icon="star"),
    ).add_to(m)
    folium.LayerControl().add_to(m)
    return m._repr_html_()


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _generate_report(lat, lon, analysis_dates, shadow_summary, height_ft,
                     affected_site_count, sites_hit_detail):
    height_str = f"{height_ft:.0f} ft ({height_ft * 0.3048:.1f} m)" if height_ft else "N/A"
    lines = [
        "CEQR Chapter 8 — Incremental Shadow Analysis",
        "=" * 44,
        "",
        f"Project Location : {lat:.5f}N, {abs(lon):.5f}W",
        f"Building Height  : {height_str}",
        f"Analysis Method  : Incremental shadow (With-Action minus No-Action)",
        f"Solar Calculator : pysolar (accurate ephemeris)",
        f"Time Zone        : EST (no daylight savings)",
        "",
        "ANALYSIS DATES",
        "-" * 14,
    ]
    for d in analysis_dates:
        s = shadow_summary.get(d, {})
        lines.append(f"  {d}")
        lines.append(f"    Max incremental shadow area : {s.get('max_incremental_area_sqft', 0):,.0f} sq ft")
        lines.append(f"    Affected sites              : {s.get('affected_site_count', 0)}")
        lines.append(f"    Shadow window (EST)         : {s.get('first_shadow', 'N/A')} – {s.get('last_shadow', 'N/A')}")
        lines.append("")

    lines += [
        "SENSITIVE SITE IMPACTS",
        "-" * 22,
        f"Sites receiving incremental shadow: {affected_site_count}",
        "",
    ]

    if sites_hit_detail:
        for site_name, date_impacts in sorted(sites_hit_detail.items()):
            lines.append(f"  {site_name}")
            for d, times in sorted(date_impacts.items()):
                times_sorted = sorted(times)
                enter = times_sorted[0].strftime("%H:%M")
                exit_ = times_sorted[-1].strftime("%H:%M")
                dur = int((times_sorted[-1] - times_sorted[0]).total_seconds() / 60)
                lines.append(f"    {d}: shadow {enter}–{exit_} EST ({dur} min)")
            lines.append("")
    else:
        lines.append("  No sensitive sites receive incremental shadow.")
        lines.append("")

    lines += [
        "CONCLUSION",
        "-" * 10,
    ]
    if affected_site_count > 0:
        lines.append(
            f"The proposed building casts incremental shadow on {affected_site_count} "
            "sensitive site(s) during the CEQR analysis period. A detailed shadow analysis "
            "per CEQR Chapter 8 Section 320 is warranted."
        )
    else:
        lines.append(
            "The proposed building does not cast incremental shadow on any identified "
            "sensitive sites. No further shadow analysis is required."
        )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def execute(inputs):
    import geopandas as gpd
    from pysolar.solar import get_altitude, get_azimuth
    from shapely.geometry import mapping
    from shapely.ops import unary_union

    # ------------------------------------------------------------------
    # 1. Resolve inputs
    # ------------------------------------------------------------------
    no_action_obj = inputs.get("no_action_mesh_obj") or ""
    with_action_obj = inputs.get("with_action_mesh_obj") or ""

    if not with_action_obj:
        raise ValueError("with_action_mesh_obj is required.")

    project_location = inputs.get("project_location")
    if not project_location:
        raise ValueError("project_location is required.")
    if isinstance(project_location, (list, tuple)):
        lat, lon = float(project_location[0]), float(project_location[1])
    else:
        lat = float(project_location.get("lat", project_location.get("latitude")))
        lon = float(project_location.get("lon", project_location.get("longitude")))

    analysis_dates = inputs.get("analysis_dates")
    if not analysis_dates:
        raise ValueError("analysis_dates is required.")

    interval_min = int(inputs.get("analysis_interval_min") or DEFAULT_INTERVAL_MIN)
    height_ft = inputs.get("building_height_ft")
    if height_ft:
        height_ft = float(height_ft)

    # ------------------------------------------------------------------
    # 2. Set up coordinates
    # ------------------------------------------------------------------
    wgs_to_utm, utm_to_wgs = _get_utm_transformers(lon, lat)
    cx_utm, cy_utm = wgs_to_utm.transform(lon, lat)

    # ------------------------------------------------------------------
    # 3. Parse OBJ meshes and translate to UTM
    # ------------------------------------------------------------------
    verts_na_local, faces_na = _parse_obj(no_action_obj)
    verts_wa_local, faces_wa = _parse_obj(with_action_obj)

    verts_na_utm = _local_to_utm(verts_na_local, cx_utm, cy_utm)
    verts_wa_utm = _local_to_utm(verts_wa_local, cx_utm, cy_utm)

    if not verts_wa_utm or not faces_wa:
        raise ValueError("with_action_mesh_obj contains no usable geometry.")

    # ------------------------------------------------------------------
    # 4. Load sensitive sites
    # ------------------------------------------------------------------
    sites_gdf = _load_sensitive_sites(inputs.get("sensitive_sites_geojson"))
    if sites_gdf is not None and sites_gdf.crs is None:
        sites_gdf = sites_gdf.set_crs(epsg=4326)
    utm_epsg = int(
        ("326" if lat >= 0 else "327") + str(int((lon + 180) / 6) + 1)
    )
    if sites_gdf is not None:
        sites_utm = sites_gdf.to_crs(epsg=utm_epsg)
        sites_sindex = sites_utm.sindex  # spatial index — built once, reused every timestep
    else:
        sites_utm = None
        sites_sindex = None

    # ------------------------------------------------------------------
    # 5. Iterate over analysis dates and times
    # ------------------------------------------------------------------
    incremental_features = []    # GeoJSON features for output
    sites_hit_detail = {}        # site_name → {date → [datetimes]}
    shadow_summary = {}          # date → summary dict

    for date_str in analysis_dates:
        try:
            year, month, day = map(int, date_str.split("-"))
        except ValueError:
            continue

        times = _analysis_times(lat, lon, year, month, day, interval_min)
        date_incremental_areas = []
        date_first_shadow = None
        date_last_shadow = None
        date_affected_sites = set()

        for dt in times:
            alt = get_altitude(lat, lon, dt)
            if alt <= MIN_SOLAR_ALT:
                continue
            az = get_azimuth(lat, lon, dt)

            # Project No-Action shadow
            shadow_na = _project_shadow(verts_na_utm, faces_na, alt, az) if (verts_na_utm and faces_na) else None

            # Project With-Action shadow
            shadow_wa = _project_shadow(verts_wa_utm, faces_wa, alt, az)
            if shadow_wa is None:
                continue

            # Incremental shadow
            if shadow_na is not None and not shadow_na.is_empty:
                try:
                    incremental = shadow_wa.difference(shadow_na)
                except Exception:
                    incremental = shadow_wa
            else:
                incremental = shadow_wa

            if incremental is None or incremental.is_empty:
                continue

            area_m2 = incremental.area
            area_sqft = area_m2 * 10.7639

            # Convert to WGS84
            poly_wgs = _poly_to_wgs(incremental, utm_to_wgs)
            if poly_wgs is None or poly_wgs.is_empty:
                continue

            time_str = dt.strftime("%H:%M")
            incremental_features.append({
                "type": "Feature",
                "geometry": mapping(poly_wgs),
                "properties": {
                    "date": date_str,
                    "time_est": time_str,
                    "solar_altitude_deg": round(alt, 2),
                    "solar_azimuth_deg": round(az, 2),
                    "incremental_area_sqft": round(area_sqft, 0),
                    "incremental_area_m2": round(area_m2, 1),
                },
            })

            date_incremental_areas.append(area_sqft)
            if date_first_shadow is None:
                date_first_shadow = time_str
            date_last_shadow = time_str

            # Intersect with sensitive sites via spatial index
            if sites_utm is not None and sites_sindex is not None:
                try:
                    candidate_idxs = list(sites_sindex.intersection(incremental.bounds))
                    candidates = sites_utm.iloc[candidate_idxs]
                    hits = candidates[candidates.intersects(incremental)]
                    for idx, row in hits.iterrows():
                        name = _site_name(row, idx)
                        date_affected_sites.add(name)
                        if name not in sites_hit_detail:
                            sites_hit_detail[name] = {}
                        sites_hit_detail[name].setdefault(date_str, []).append(dt)
                except Exception:
                    pass

        shadow_summary[date_str] = {
            "max_incremental_area_sqft": round(max(date_incremental_areas), 0) if date_incremental_areas else 0,
            "affected_site_count": len(date_affected_sites),
            "first_shadow": date_first_shadow or "N/A",
            "last_shadow": date_last_shadow or "N/A",
        }

    # ------------------------------------------------------------------
    # 6. Build affected-sites GeoJSON
    # ------------------------------------------------------------------
    affected_names = set(sites_hit_detail.keys())
    affected_site_count = len(affected_names)

    affected_sites_gdf = None
    unaffected_sites_gdf = None
    affected_sites_geojson = {"type": "FeatureCollection", "features": []}

    if sites_gdf is not None:
        def get_name(row, idx):
            return _site_name(row, idx)

        sites_gdf = sites_gdf.copy()
        sites_gdf["_name"] = [get_name(row, idx) for idx, row in sites_gdf.iterrows()]
        affected_sites_gdf = sites_gdf[sites_gdf["_name"].isin(affected_names)]
        unaffected_sites_gdf = sites_gdf[~sites_gdf["_name"].isin(affected_names)]

        if not affected_sites_gdf.empty:
            for col in affected_sites_gdf.select_dtypes(include=["datetime64"]).columns:
                affected_sites_gdf = affected_sites_gdf.copy()
                affected_sites_gdf[col] = affected_sites_gdf[col].astype(str)
            affected_sites_geojson = json.loads(affected_sites_gdf.to_json())

    # ------------------------------------------------------------------
    # 7. Visualization
    # ------------------------------------------------------------------
    viz_html = _build_map(
        incremental_features,
        affected_sites_gdf if affected_sites_gdf is not None and not affected_sites_gdf.empty else None,
        unaffected_sites_gdf if unaffected_sites_gdf is not None and not unaffected_sites_gdf.empty else None,
        lat, lon,
    )

    # ------------------------------------------------------------------
    # 8. Report
    # ------------------------------------------------------------------
    report = _generate_report(
        lat, lon, analysis_dates, shadow_summary, height_ft,
        affected_site_count, sites_hit_detail,
    )

    # ------------------------------------------------------------------
    # 9. Return outputs
    # ------------------------------------------------------------------
    return {
        "incremental_shadows_geojson": {
            "type": "FeatureCollection",
            "features": incremental_features,
        },
        "affected_sites_geojson": affected_sites_geojson,
        "shadow_summary": shadow_summary,
        "affected_site_count": affected_site_count,
        "summary_report": report,
        "visualization": viz_html,
    }


# ---------------------------------------------------------------------------
# Standalone test (requires Modules A + B outputs)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    sys.path.insert(0, "../shadow-context-builder")
    sys.path.insert(0, "../shadow-pipeline-builder")

    import shadow_context_builder as A
    import shadow_pipeline_builder as B

    test_footprint = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [[
                [-73.9840, 40.7530], [-73.9825, 40.7530],
                [-73.9825, 40.7542], [-73.9840, 40.7542], [-73.9840, 40.7530],
            ]]},
            "properties": {},
        }],
    }

    print("Module A — fetching context buildings...")
    a = A.execute({
        "building_height_ft": 400,
        "study_area_radius_ft": 1000,
        "project_location": [40.7536, -73.9832],
    })
    print(f"  {a['building_count']} buildings, OBJ {len(a['context_mesh_obj']):,} chars")

    print("Module B — assembling scenes...")
    b = B.execute({
        "building_geojson": test_footprint,
        "building_height_ft": 400,
        "project_location": a["project_location"],
        "context_mesh_obj": a["context_mesh_obj"],
        "study_area_radius_ft": a["study_area_radius_ft"],
        # Use only Dec 21 for a faster test
        "analysis_dates": ["2026-12-21"],
    })
    print(f"  Dates: {b['analysis_dates']}")
    print(f"  No-action OBJ: {len(b['no_action_mesh_obj']):,} chars")
    print(f"  With-action OBJ: {len(b['with_action_mesh_obj']):,} chars")

    print("Module C — computing incremental shadows...")
    c = execute({
        "no_action_mesh_obj": b["no_action_mesh_obj"],
        "with_action_mesh_obj": b["with_action_mesh_obj"],
        "project_location": b["project_location"],
        "analysis_dates": b["analysis_dates"],
        "analysis_year": b["analysis_year"],
        "building_height_ft": 400,
    })
    print(f"  Incremental shadow snapshots: {len(c['incremental_shadows_geojson']['features'])}")
    print(f"  Affected sites: {c['affected_site_count']}")
    print(f"  Shadow summary: {c['shadow_summary']}")
    print()
    print(c["summary_report"])
