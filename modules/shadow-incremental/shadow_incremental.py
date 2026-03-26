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
    from shapely.geometry import Polygon, MultiPolygon, GeometryCollection
    if polygon is None or polygon.is_empty:
        return None

    # Normalize GeometryCollection (produced by .difference() on near-identical polygons)
    # by extracting only the polygon parts.
    if polygon.geom_type == "GeometryCollection":
        polys = [g for g in polygon.geoms if g.geom_type in ("Polygon", "MultiPolygon")]
        if not polys:
            return None
        from shapely.ops import unary_union
        polygon = unary_union(polys)
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

def _prefilter_faces(vertices_utm, faces):
    """
    Pre-filter: return only faces with at least one vertex above ground (z > 0.1).
    Also resolves vertex indices and stores pre-fetched vertex tuples per face.
    Returns list of (ground_pts, max_z) tuples for use in _project_shadow_fast.
    """
    n = len(vertices_utm)
    active = []
    for face in faces:
        verts = [vertices_utm[i] for i in face if 0 <= i < n]
        if len(verts) < 3:
            continue
        mz = max(v[2] for v in verts)
        if mz > 0.1:
            active.append(verts)
    return active


def _project_shadow(active_faces, solar_altitude_deg, solar_azimuth_deg):
    """
    Per-face shadow projection from pre-filtered face list.
    active_faces: list of vertex tuples [(x,y,z), ...] — already ground-filtered.
    Returns a Shapely polygon (UTM) or None.
    """
    from shapely.geometry import MultiPoint
    from shapely.ops import unary_union

    if solar_altitude_deg <= MIN_SOLAR_ALT:
        return None
    if not active_faces:
        return None

    tan_alt = math.tan(math.radians(solar_altitude_deg))
    shadow_az_rad = math.radians((solar_azimuth_deg + 180.0) % 360.0)
    sin_az = math.sin(shadow_az_rad)
    cos_az = math.cos(shadow_az_rad)
    scale = 1.0 / tan_alt

    shadow_polys = []
    for verts in active_faces:
        ground_pts = [(v[0], v[1]) for v in verts]
        tip_pts = [
            (v[0] + v[2] * scale * sin_az, v[1] + v[2] * scale * cos_az)
            if v[2] > 0.1 else (v[0], v[1])
            for v in verts
        ]
        all_pts = ground_pts + tip_pts
        try:
            hull = MultiPoint(all_pts).convex_hull
            if hull.is_valid and not hull.is_empty and hull.area > 0:
                shadow_polys.append(hull)
        except Exception:
            continue

    if not shadow_polys:
        return None
    # Cascade union in chunks of 32 to keep individual merges fast
    while len(shadow_polys) > 1:
        next_level = []
        for i in range(0, len(shadow_polys), 32):
            chunk = shadow_polys[i:i + 32]
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
# Tier 3 schedule extraction
# ---------------------------------------------------------------------------

def _schedule_from_tier3(sites_affected, interval_min):
    """
    Build analysis schedule from Tier 3 sites_affected output.
    Returns {date_str: [datetime, ...]} with exactly the timesteps where
    Tier 3 detected shadow on at least one site (no margin — Tier 3 already
    found the windows; we just need to verify the incremental contribution).

    sites_affected format (from shadow_tier3_projection):
      [{site_name, date_impacts: [{date, shadow_enter, shadow_exit, ...}]}]
    """
    schedule = {}  # date_str -> set of datetimes
    step = timedelta(minutes=interval_min)

    for site in (sites_affected or []):
        for di in site.get("date_impacts", []):
            date_str = di.get("date", "")
            if not date_str:
                continue
            enter_str = di.get("shadow_enter", "").replace(" EST", "").strip()
            exit_str  = di.get("shadow_exit",  "").replace(" EST", "").strip()
            try:
                year, month, day = map(int, date_str.split("-"))
                eh, em = map(int, enter_str.split(":"))
                xh, xm = map(int, exit_str.split(":"))
            except (ValueError, AttributeError):
                continue
            enter_dt = datetime(year, month, day, eh, em, tzinfo=EST)
            exit_dt  = datetime(year, month, day, xh, xm, tzinfo=EST)
            # Step through the exact shadow window at interval_min increments
            t = enter_dt
            while t <= exit_dt:
                schedule.setdefault(date_str, set()).add(t)
                t += step

    return {d: sorted(ts) for d, ts in schedule.items()}


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

def _build_map(incremental_features, affected_sites_gdf, unaffected_sites_gdf, lat, lon,
               utm_epsg=None, cx_utm=None, cy_utm=None):
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
                "fillColor": c, "color": c, "weight": 1.5, "fillOpacity": 0.5,
            },
            tooltip=folium.GeoJsonTooltip(
                fields=["time_est", "solar_altitude_deg", "incremental_area_sqft"],
                aliases=["Time (EST):", "Solar altitude (°):", "New shadow area (sq ft):"],
            ),
        ).add_to(m)

    if unaffected_sites_gdf is not None and not unaffected_sites_gdf.empty:
        # Cap unaffected sites in map — drawing all 2000+ parks creates a huge HTML file.
        # Show only the closest 200 to keep the visualization fast.
        try:
            if utm_epsg and cx_utm is not None:
                from shapely.geometry import Point as _Pt
                uf_utm = unaffected_sites_gdf.copy().to_crs(epsg=utm_epsg)
                center_utm = _Pt(cx_utm, cy_utm)
                uf_utm["_dist"] = uf_utm.geometry.centroid.distance(center_utm)
                uf = uf_utm.nsmallest(200, "_dist").to_crs(epsg=4326)
            else:
                uf = unaffected_sites_gdf.head(200)
        except Exception:
            uf = unaffected_sites_gdf.head(200)
        folium.GeoJson(
            json.loads(uf.to_json()),
            name="Sensitive sites — no incremental shadow (nearest 200)",
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

    if not with_action_obj and not inputs.get("project_mesh_obj"):
        raise ValueError("Either project_mesh_obj or with_action_mesh_obj is required.")

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
    # No-Action mesh: context buildings only (always needed)
    verts_na_local, faces_na = _parse_obj(no_action_obj)
    verts_na_utm = _local_to_utm(verts_na_local, cx_utm, cy_utm)
    active_na = _prefilter_faces(verts_na_utm, faces_na)

    # Project-building-only mesh (preferred) vs. With-Action mesh (fallback).
    #
    # Preferred — project_mesh_obj:
    #   Compute shadow from the project building ALONE, then subtract context
    #   coverage. Avoids the floating-point precision issue that occurs when
    #   differencing two large cascaded unions (WA − NA): tiny differences in
    #   how hundreds of context-building polygons are merged can create phantom
    #   incremental regions anywhere in the scene.
    #
    # Fallback — with_action_mesh_obj:
    #   Legacy approach (context + project combined). Less precise but still
    #   works when project_mesh_obj is not wired.
    project_mesh_obj_str = inputs.get("project_mesh_obj")
    if project_mesh_obj_str:
        verts_proj_local, faces_proj = _parse_obj(project_mesh_obj_str)
        verts_proj_utm = _local_to_utm(verts_proj_local, cx_utm, cy_utm)
        active_proj = _prefilter_faces(verts_proj_utm, faces_proj)
        active_wa = None
        print(
            f"[shadow_incremental] Active faces: NA={len(active_na)}, proj-only={len(active_proj)} (direct mode)",
            flush=True,
        )
    else:
        verts_wa_local, faces_wa = _parse_obj(with_action_obj)
        verts_wa_utm = _local_to_utm(verts_wa_local, cx_utm, cy_utm)
        if not verts_wa_utm or not faces_wa:
            raise ValueError("with_action_mesh_obj contains no usable geometry.")
        active_wa = _prefilter_faces(verts_wa_utm, faces_wa)
        active_proj = None
        print(
            f"[shadow_incremental] Active faces: NA={len(active_na)}, WA={len(active_wa)} (WA−NA mode)",
            flush=True,
        )

    # ------------------------------------------------------------------
    # 4. Load sensitive sites
    # ------------------------------------------------------------------
    # Accept 'sensitive_sites' (standard chain key from Tier 2) or legacy 'sensitive_sites_geojson'
    sites_gdf = _load_sensitive_sites(
        inputs.get("sensitive_sites") or inputs.get("sensitive_sites_geojson")
    )
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
    # 4b. Pre-compute site bearings + distances for timestep pre-filter
    # ------------------------------------------------------------------
    # Shadow from the building can only reach a site when the sun is roughly
    # in the OPPOSITE direction (shadow direction ≈ site bearing from building).
    # Pre-computing this lets us skip _project_shadow entirely for most timesteps.
    BEARING_TOL = 60.0  # degrees — generous to account for building width/depth

    if sites_utm is not None and not sites_utm.empty:
        site_bearings = []   # bearing from building centroid to each site (degrees from north)
        site_distances = []  # straight-line distance in metres
        for geom in sites_utm.geometry:
            sc = geom.centroid
            dx, dy = sc.x - cx_utm, sc.y - cy_utm
            dist = math.sqrt(dx * dx + dy * dy)
            bearing = math.degrees(math.atan2(dx, dy)) % 360  # atan2(E,N) = clockwise from north
            site_bearings.append(bearing)
            site_distances.append(dist)
        min_site_dist = min(site_distances) if site_distances else 0.0
        print(
            f"[shadow_incremental] {len(site_bearings)} sites; nearest {min_site_dist:.0f} m away",
            flush=True,
        )
    else:
        site_bearings = []
        min_site_dist = 0.0

    # Max building height — use project-only faces if available (more accurate),
    # otherwise fall back to the WA mesh (which includes context buildings).
    _height_source = active_proj if active_proj else active_wa
    max_bldg_height_m = max(
        (max(v[2] for v in face) for face in _height_source), default=100.0
    )

    def _shadow_can_reach_sites(solar_az_deg, solar_alt_deg):
        """Return True if shadow direction and length could reach any site."""
        if not site_bearings:
            return True  # no site info → always compute (conservative)
        shadow_dir = (solar_az_deg + 180.0) % 360.0
        # Check shadow is long enough to reach nearest site
        if solar_alt_deg > 0.1:
            shadow_len = max_bldg_height_m / math.tan(math.radians(solar_alt_deg))
            if shadow_len < min_site_dist * 0.5:  # 0.5 factor: building footprint adds reach
                return False
        # Check bearing matches at least one site
        return any(
            abs((shadow_dir - b + 180.0) % 360.0 - 180.0) <= BEARING_TOL
            for b in site_bearings
        )

    # ------------------------------------------------------------------
    # 5. Build analysis schedule
    # ------------------------------------------------------------------
    # If Tier 3 sites_affected is available, use only the windows where
    # Tier 3 already found shadow on a sensitive site — no need to scan
    # the full CEQR day. Otherwise fall back to full CEQR time sweep.
    tier3_sites_affected = inputs.get("sites_affected")
    if tier3_sites_affected:
        tier3_schedule_raw = _schedule_from_tier3(tier3_sites_affected, interval_min)
        # Tier 3 may use a different analysis year (e.g. 2024 metadata defaults vs 2026 pipeline year).
        # Match on MM-DD only, then remap datetimes to the correct analysis year.
        tier3_md_to_key = {k[5:]: k for k in tier3_schedule_raw}  # "12-21" -> "2024-12-21"
        dates_to_analyze = []
        tier3_schedule = {}
        for d in analysis_dates:
            md = d[5:]  # "12-21" from "2026-12-21"
            if md in tier3_md_to_key:
                src_key = tier3_md_to_key[md]
                target_year = int(d[:4])
                remapped = [dt.replace(year=target_year) for dt in tier3_schedule_raw[src_key]]
                dates_to_analyze.append(d)
                tier3_schedule[d] = remapped
        print(
            f"[shadow_incremental] Using Tier 3 schedule: {len(dates_to_analyze)} dates, "
            f"{sum(len(v) for v in tier3_schedule.values())} total timesteps",
            flush=True,
        )
    else:
        tier3_schedule = None
        dates_to_analyze = list(analysis_dates)
        print(f"[shadow_incremental] Full CEQR sweep: {len(dates_to_analyze)} dates", flush=True)

    # ------------------------------------------------------------------
    # 6. Iterate over analysis dates and times
    # ------------------------------------------------------------------
    incremental_features = []    # GeoJSON features for output
    sites_hit_detail = {}        # site_name → {date → [datetimes]}
    shadow_summary = {}          # date → summary dict

    for date_str in dates_to_analyze:
        try:
            year, month, day = map(int, date_str.split("-"))
        except ValueError:
            continue

        if tier3_schedule:
            times = tier3_schedule[date_str]
        else:
            times = _analysis_times(lat, lon, year, month, day, interval_min)
        print(f"[shadow_incremental] {date_str}: {len(times)} timesteps", flush=True)
        date_incremental_areas = []
        date_first_shadow = None
        date_last_shadow = None
        date_affected_sites = set()

        for t_idx, dt in enumerate(times):
            alt = get_altitude(lat, lon, dt)
            if alt <= MIN_SOLAR_ALT:
                continue
            az = get_azimuth(lat, lon, dt)

            # Skip this timestep if shadow direction can't reach any triggered site
            if not _shadow_can_reach_sites(az, alt):
                print(f"[shadow_incremental]   {dt.strftime('%H:%M')} — skipped (shadow direction away from sites)", flush=True)
                continue

            print(f"[shadow_incremental]   {dt.strftime('%H:%M')} alt={alt:.1f}° az={az:.1f}°", flush=True)

            # Context (No-Action) shadow — shared between both modes
            shadow_na = _project_shadow(active_na, alt, az) if active_na else None

            # Incremental shadow
            if active_proj is not None:
                # Direct mode: project shadow from the project building only, then
                # subtract wherever context buildings already cover the ground.
                # Much more precise than WA−NA because we diff a small clean polygon
                # against the context union, avoiding inter-union floating-point drift.
                shadow_proj = _project_shadow(active_proj, alt, az)
                if shadow_proj is None:
                    continue
                if shadow_na is not None and not shadow_na.is_empty:
                    try:
                        incremental = shadow_proj.difference(shadow_na).buffer(0)
                    except Exception:
                        incremental = shadow_proj
                else:
                    incremental = shadow_proj
            else:
                # Fallback: WA − NA large-union difference
                shadow_wa = _project_shadow(active_wa, alt, az)
                if shadow_wa is None:
                    continue
                if shadow_na is not None and not shadow_na.is_empty:
                    try:
                        incremental = shadow_wa.difference(shadow_na).buffer(0)
                    except Exception:
                        incremental = shadow_wa
                else:
                    incremental = shadow_wa

            # Filter tiny polygon parts — numerical slivers from difference edges
            MIN_SLIVER_M2 = 25.0  # ~270 sq ft
            if incremental.geom_type in ("MultiPolygon", "GeometryCollection"):
                from shapely.ops import unary_union as _uu2
                parts = [g for g in incremental.geoms
                         if g.geom_type in ("Polygon", "MultiPolygon") and g.area >= MIN_SLIVER_M2]
                if not parts:
                    continue
                incremental = _uu2(parts)
            elif incremental.geom_type == "Polygon" and incremental.area < MIN_SLIVER_M2:
                continue

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
    print(f"[shadow_incremental] Building visualization ({len(incremental_features)} shadow snapshots)...", flush=True)
    viz_html = _build_map(
        incremental_features,
        affected_sites_gdf if affected_sites_gdf is not None and not affected_sites_gdf.empty else None,
        unaffected_sites_gdf if unaffected_sites_gdf is not None and not unaffected_sites_gdf.empty else None,
        lat, lon,
        utm_epsg=utm_epsg, cx_utm=cx_utm, cy_utm=cy_utm,
    )

    # ------------------------------------------------------------------
    # 8. Report
    # ------------------------------------------------------------------
    report = _generate_report(
        lat, lon, analysis_dates, shadow_summary, height_ft,
        affected_site_count, sites_hit_detail,
    )

    # ------------------------------------------------------------------
    # 9. Build triggered_sites — primary site-centric output
    # ------------------------------------------------------------------
    triggered_sites = {}
    for site_name, date_impacts in sites_hit_detail.items():
        triggered_sites[site_name] = {}
        for date_str, datetimes in date_impacts.items():
            sorted_dts = sorted(datetimes)
            entry = sorted_dts[0]
            exit_ = sorted_dts[-1]
            duration_min = int((exit_ - entry).total_seconds() / 60)
            triggered_sites[site_name][date_str] = {
                "shadow_entry_est": entry.strftime("%H:%M"),
                "shadow_exit_est": exit_.strftime("%H:%M"),
                "duration_min": duration_min,
                "timesteps_affected": len(sorted_dts),
            }

    # ------------------------------------------------------------------
    # 10. Return outputs
    # ------------------------------------------------------------------
    return {
        "triggered_sites": triggered_sites,
        "affected_sites_geojson": affected_sites_geojson,
        "shadow_summary": shadow_summary,
        "affected_site_count": affected_site_count,
        "incremental_shadows_geojson": {
            "type": "FeatureCollection",
            "features": incremental_features,
        },
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
