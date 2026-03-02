"""
Shadow Tier 3: 3D Model (OBJ) Input Module

Same CEQR methodology as shadow_tier3_projection, but accepts a real 3D building
model (.obj file) instead of a 2D footprint + uniform height. This produces more
accurate shadows for buildings with setbacks, tapered profiles, or complex massing.

Algorithm:
  1. Parse OBJ vertices → list of (x, y, z) in local model space
  2. Align model to UTM: center at building_geojson footprint centroid, apply rotation
  3. For each analysis datetime + solar position:
       - For every vertex: project its shadow tip onto the ground plane
         (shadow_length = z / tan(solar_altitude))
       - Shadow polygon = convex hull of all vertex projections + their shadow tips
  4. Intersect shadow polygons with sensitive sites → impact summary

CEQR NYC representative days: Dec 21, Mar 21, May 6, Jun 21
Time window: 1.5h after sunrise to 1.5h before sunset (EST, no DST)
"""
import json
import math
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path

import folium
import geopandas as gpd
import numpy as np
from pyproj import Transformer
from pysolar.solar import get_altitude, get_azimuth
from shapely.geometry import MultiPoint, Polygon, mapping
from shapely.ops import unary_union

warnings.filterwarnings('ignore', message="I don't know about leap seconds")

EST = timezone(timedelta(hours=-5))

CEQR_ANALYSIS_DATES = {
    'NYC': ['2024-12-21', '2024-03-21', '2024-05-06', '2024-06-21'],
    'generic': ['2024-12-21', '2024-03-21', '2024-06-21'],
}

ANALYSIS_INTERVAL_MIN = 60


# ---------------------------------------------------------------------------
# OBJ parsing + georeferencing
# ---------------------------------------------------------------------------

def parse_obj_vertices(obj_text, up_axis='Z', scale=1.0):
    """
    Extract (x, y, z) vertices from OBJ file text.
    If up_axis='Y' (SketchUp/OpenGL), swaps Y and Z so that Z always = height.
    scale converts from model units to meters (e.g. 0.01 for centimeters, 0.0254 for inches).
    """
    vertices = []
    for line in obj_text.splitlines():
        parts = line.strip().split()
        if not parts or parts[0] != 'v':
            continue
        try:
            x, y, z = float(parts[1]), float(parts[2]), float(parts[3])
        except (IndexError, ValueError):
            continue
        if up_axis == 'Y':
            x, y, z = x, -z, y   # Y-up to Z-up: swap y/z, negate depth
        vertices.append((x * scale, y * scale, z * scale))
    return vertices


def align_obj_to_utm(vertices, cx_utm, cy_utm, rotation_deg=0.0):
    """
    Translate + rotate OBJ vertices so their XY centroid sits at (cx_utm, cy_utm)
    in UTM coordinates.

    rotation_deg: degrees CW from north that the model's +Y axis points.
      0   = model +Y already points north
      29  = Manhattan street grid (model +Y points NNE)
    """
    if not vertices:
        return []

    xs = [v[0] for v in vertices]
    ys = [v[1] for v in vertices]
    local_cx = (max(xs) + min(xs)) / 2.0
    local_cy = (max(ys) + min(ys)) / 2.0

    # CW rotation in geographic convention = CCW in standard math convention
    theta = math.radians(-rotation_deg)
    cos_t = math.cos(theta)
    sin_t = math.sin(theta)

    result = []
    for x, y, z in vertices:
        lx = x - local_cx
        ly = y - local_cy
        rx = lx * cos_t - ly * sin_t
        ry = lx * sin_t + ly * cos_t
        result.append((cx_utm + rx, cy_utm + ry, z))

    return result


# ---------------------------------------------------------------------------
# Shadow projection (per-vertex, replaces uniform extrusion)
# ---------------------------------------------------------------------------

def project_shadow_from_vertices(vertices_3d_utm, solar_altitude_deg, solar_azimuth_deg):
    """
    Project the shadow of a 3D building (arbitrary vertex cloud) onto the ground.

    For each vertex at height z:
      shadow_tip = (x + z/tan(alt) * sin(az+180), y + z/tan(alt) * cos(az+180))

    Shadow polygon = convex hull of all ground projections + all shadow tips.
    """
    if solar_altitude_deg <= 2.0:
        return None

    tan_alt = math.tan(math.radians(solar_altitude_deg))
    shadow_az_rad = math.radians((solar_azimuth_deg + 180.0) % 360.0)
    sin_az = math.sin(shadow_az_rad)
    cos_az = math.cos(shadow_az_rad)

    pts = []
    for x, y, z in vertices_3d_utm:
        pts.append((x, y))          # vertex projected to ground
        if z > 0.1:                 # only meaningful height contributes shadow
            shadow_len = z / tan_alt
            pts.append((x + shadow_len * sin_az, y + shadow_len * cos_az))

    if len(pts) < 3:
        return None

    hull = MultiPoint(pts).convex_hull
    return hull if hull.is_valid else None


def transform_polygon_to_wgs(polygon_utm, utm_to_wgs):
    """Transform a Shapely polygon from UTM to WGS84."""
    if polygon_utm.geom_type == 'Polygon':
        coords = list(polygon_utm.exterior.coords)
        wgs_coords = [utm_to_wgs.transform(x, y) for x, y in coords]
        return Polygon(wgs_coords)
    return polygon_utm


# ---------------------------------------------------------------------------
# Solar helpers (identical to shadow_tier3_projection)
# ---------------------------------------------------------------------------

def get_utm_transformers(lon, lat):
    zone = int((lon + 180) / 6) + 1
    epsg = 32600 + zone if lat >= 0 else 32700 + zone
    utm_crs = f'EPSG:{epsg}'
    wgs_to_utm = Transformer.from_crs('EPSG:4326', utm_crs, always_xy=True)
    utm_to_wgs = Transformer.from_crs(utm_crs, 'EPSG:4326', always_xy=True)
    return utm_crs, wgs_to_utm, utm_to_wgs


def find_sunrise_sunset(lat, lon, year, month, day):
    sunrise = None
    sunset = None
    prev_above = False
    for hour in range(4, 22):
        for minute in range(0, 60):
            dt = datetime(year, month, day, hour, minute, 0, tzinfo=EST)
            alt = get_altitude(lat, lon, dt)
            above = alt > 0
            if above and not prev_above:
                sunrise = dt
            if not above and prev_above and sunrise is not None:
                sunset = dt
            prev_above = above
    return sunrise, sunset


# ---------------------------------------------------------------------------
# Output helpers (identical to shadow_tier3_projection)
# ---------------------------------------------------------------------------

def build_site_impact_summary(sites_hit):
    summary = []
    for site_name, datetimes in sites_hit.items():
        if not datetimes:
            continue
        datetimes_sorted = sorted(datetimes)
        by_date = {}
        for dt in datetimes_sorted:
            d = dt.strftime('%Y-%m-%d')
            by_date.setdefault(d, []).append(dt)
        date_impacts = []
        for date, dts in by_date.items():
            date_impacts.append({
                'date': date,
                'shadow_enter': min(dts).strftime('%H:%M EST'),
                'shadow_exit': max(dts).strftime('%H:%M EST'),
                'duration_minutes': int((max(dts) - min(dts)).total_seconds() / 60),
            })
        summary.append({
            'site_name': site_name,
            'analysis_days_affected': len(by_date),
            'date_impacts': date_impacts,
        })
    return summary


def generate_report(height_m, n_vertices, lat, lon, jurisdiction,
                    analysis_dates, shadow_features, sites_affected):
    n_shadows = len(shadow_features)
    n_sites = len(sites_affected)

    report = f"""Shadow Tier 3: 3D Model Screening Results
==========================================

Building Model: OBJ ({n_vertices} vertices, max height {height_m:.1f} m / {height_m / 0.3048:.0f} ft)
Location: {round(lat, 4)}N, {round(abs(lon), 4)}W
Jurisdiction: {jurisdiction}
Analysis Method: CEQR Technical Manual Chapter 8, Sections 314-314.5
Solar Calculator: pysolar (accurate ephemeris)
Shadow Projection: Per-vertex 3D projection with UTM coordinate geometry

ANALYSIS PARAMETERS
-------------------
Representative Days: {', '.join(analysis_dates)}
Time Window: 1.5 hours after sunrise to 1.5 hours before sunset
Time Zone: Eastern Standard Time (no daylight savings)
Analysis Interval: {ANALYSIS_INTERVAL_MIN} minutes
Total Shadow Snapshots: {n_shadows}

SENSITIVE SITE IMPACTS
----------------------
Sites receiving shadow: {n_sites}

"""
    if sites_affected:
        for site in sites_affected:
            report += f"  Site: {site['site_name']}\n"
            report += f"  Analysis days affected: {site['analysis_days_affected']}\n"
            for di in site['date_impacts']:
                report += (f"    {di['date']}: shadow {di['shadow_enter']} - "
                           f"{di['shadow_exit']} ({di['duration_minutes']} min)\n")
            report += "\n"
    else:
        report += "  No sensitive sites receive shadow from the proposed building.\n\n"

    report += "CONCLUSION\n----------\n"
    if sites_affected:
        report += (f"Shadows from the proposed 3D building model reach {n_sites} sensitive site(s).\n"
                   "A detailed shadow analysis (Section 320) is warranted.\n")
    else:
        report += "No shadows reach any identified sensitive sites. No further analysis required.\n"

    return report


def create_visualization(building_gdf, shadow_features, sites_gdf, sites_hit, lat, lon):
    m = folium.Map(location=[lat, lon], zoom_start=15, tiles='CartoDB positron')

    palette = ['#ef4444', '#f97316', '#eab308', '#22c55e',
               '#06b6d4', '#6366f1', '#a855f7', '#ec4899']
    unique_dates = sorted(set(f['properties']['date'] for f in shadow_features))
    date_colors = {d: palette[i % len(palette)] for i, d in enumerate(unique_dates)}

    for date in unique_dates:
        color = date_colors[date]
        folium.GeoJson(
            {'type': 'FeatureCollection',
             'features': [f for f in shadow_features if f['properties']['date'] == date]},
            name=f'Shadows {date}',
            style_function=lambda x, c=color: {
                'fillColor': c, 'color': c, 'weight': 0.5, 'fillOpacity': 0.2
            },
            tooltip=folium.GeoJsonTooltip(
                fields=['time_est', 'solar_altitude_deg', 'shadow_length_m'],
                aliases=['Time (EST):', 'Solar altitude (°):', 'Max shadow length (m):']
            )
        ).add_to(m)

    folium.GeoJson(
        building_gdf,
        name='Proposed Building (footprint)',
        style_function=lambda x: {
            'fillColor': '#3b82f6', 'color': '#1d4ed8', 'weight': 2, 'fillOpacity': 0.8
        },
        tooltip='Proposed Building'
    ).add_to(m)

    affected_names = set(sites_hit.keys())
    affected_feats, unaffected_feats = [], []

    for idx, row in sites_gdf.iterrows():
        name = row.get('signname', row.get('propname', row.get('name', f'Site {idx}')))
        feat = {'type': 'Feature', 'geometry': mapping(row.geometry), 'properties': {'name': name}}
        (affected_feats if name in affected_names else unaffected_feats).append(feat)

    if unaffected_feats:
        folium.GeoJson(
            {'type': 'FeatureCollection', 'features': unaffected_feats},
            name='Sensitive sites — no impact',
            style_function=lambda x: {
                'fillColor': '#a78bfa', 'color': '#7c3aed', 'weight': 1, 'fillOpacity': 0.35
            },
            tooltip=folium.GeoJsonTooltip(fields=['name'], aliases=['Site:'], sticky=False)
        ).add_to(m)

    if affected_feats:
        folium.GeoJson(
            {'type': 'FeatureCollection', 'features': affected_feats},
            name='Sensitive sites — shadow impact',
            style_function=lambda x: {
                'fillColor': '#f97316', 'color': '#c2410c', 'weight': 2, 'fillOpacity': 0.75
            },
            tooltip=folium.GeoJsonTooltip(fields=['name'], aliases=['Affected:'], sticky=False)
        ).add_to(m)

    folium.LayerControl().add_to(m)
    return m._repr_html_()


# ---------------------------------------------------------------------------
# Main execute
# ---------------------------------------------------------------------------

def execute(inputs):
    building_geojson = inputs.get('building_geojson')
    building_obj = inputs.get('building_obj')
    jurisdiction = inputs.get('jurisdiction', 'NYC')
    sensitive_sites_input = inputs.get('sensitive_sites') or inputs.get('sites_requiring_tier3')
    analysis_dates = inputs.get('analysis_dates')
    model_rotation_deg = float(inputs.get('model_rotation_deg') or 0.0)
    model_up_axis = inputs.get('model_up_axis', 'Z').upper()
    model_scale = float(inputs.get('model_scale') or 1.0)

    if not building_geojson:
        raise ValueError("building_geojson is required")
    if not building_obj:
        raise ValueError("building_obj is required (OBJ file content as string)")

    if isinstance(building_geojson, str):
        building_geojson = json.loads(building_geojson)

    building_gdf = gpd.GeoDataFrame.from_features(building_geojson['features'])
    if building_gdf.crs is None:
        building_gdf.set_crs(epsg=4326, inplace=True)

    building_union = unary_union(building_gdf.geometry)
    centroid = building_union.centroid
    lat, lon = centroid.y, centroid.x

    # Parse OBJ
    vertices_local = parse_obj_vertices(building_obj, up_axis=model_up_axis, scale=model_scale)
    if not vertices_local:
        raise ValueError("No vertices found in OBJ file. Check format and up_axis setting.")

    max_height_m = max(v[2] for v in vertices_local)

    # Set up UTM
    utm_crs, wgs_to_utm, utm_to_wgs = get_utm_transformers(lon, lat)
    cx_utm, cy_utm = wgs_to_utm.transform(lon, lat)

    # Align OBJ to UTM
    vertices_utm = align_obj_to_utm(vertices_local, cx_utm, cy_utm, model_rotation_deg)

    # Load sensitive sites
    if sensitive_sites_input:
        if isinstance(sensitive_sites_input, str):
            sensitive_sites_input = json.loads(sensitive_sites_input)
        sites_gdf = gpd.GeoDataFrame.from_features(sensitive_sites_input['features'])
        if sites_gdf.crs is None:
            sites_gdf.set_crs(epsg=4326, inplace=True)
    else:
        default_path = Path(__file__).parent.parent.parent / 'datasets' / 'nyc_dpr_parks_properties.geojson'
        if default_path.exists():
            sites_gdf = gpd.read_file(str(default_path))
            for col in sites_gdf.select_dtypes(include=['datetime64']).columns:
                sites_gdf[col] = sites_gdf[col].astype(str)
            # Apply Tier 1 buffer filter to limit scope
            shadow_radius_m = max_height_m * 4.3
            building_proj = building_gdf.to_crs(epsg=3857)
            buf = gpd.GeoDataFrame(
                geometry=building_proj.buffer(shadow_radius_m), crs='EPSG:3857'
            ).to_crs(epsg=4326)
            sites_gdf = gpd.sjoin(sites_gdf, buf, how='inner', predicate='intersects')
            if 'index_right' in sites_gdf.columns:
                sites_gdf = sites_gdf.drop(columns=['index_right'])
        else:
            sites_gdf = gpd.GeoDataFrame({'name': [], 'geometry': []}, crs='EPSG:4326')

    if not analysis_dates:
        analysis_dates = CEQR_ANALYSIS_DATES.get(jurisdiction, CEQR_ANALYSIS_DATES['generic'])

    # Run shadow analysis
    all_shadow_features = []
    sites_hit = {}

    for date_str in analysis_dates:
        year, month, day = map(int, date_str.split('-'))
        sunrise_est, sunset_est = find_sunrise_sunset(lat, lon, year, month, day)
        if sunrise_est is None:
            continue

        window_start = sunrise_est + timedelta(hours=1.5)
        window_end = sunset_est - timedelta(hours=1.5)
        if window_start >= window_end:
            continue

        current_dt = window_start
        while current_dt <= window_end:
            altitude = get_altitude(lat, lon, current_dt)
            azimuth = get_azimuth(lat, lon, current_dt)

            if altitude > 2.0:
                shadow_utm = project_shadow_from_vertices(vertices_utm, altitude, azimuth)

                if shadow_utm and shadow_utm.is_valid:
                    shadow_wgs = transform_polygon_to_wgs(shadow_utm, utm_to_wgs)
                    max_shadow_len = max_height_m / math.tan(math.radians(altitude))

                    all_shadow_features.append({
                        'type': 'Feature',
                        'geometry': mapping(shadow_wgs),
                        'properties': {
                            'date': date_str,
                            'time_est': current_dt.strftime('%H:%M'),
                            'datetime_iso': current_dt.isoformat(),
                            'solar_altitude_deg': round(altitude, 2),
                            'solar_azimuth_deg': round(azimuth, 2),
                            'shadow_length_m': round(max_shadow_len, 1),
                        }
                    })

                    for idx, site_row in sites_gdf.iterrows():
                        site_name = site_row.get('signname', site_row.get('propname',
                                     site_row.get('name', f'Site {idx}')))
                        if shadow_wgs.intersects(site_row.geometry):
                            sites_hit.setdefault(site_name, []).append(current_dt)

            current_dt += timedelta(minutes=ANALYSIS_INTERVAL_MIN)

    shadow_geojson = {'type': 'FeatureCollection', 'features': all_shadow_features}
    sites_affected = build_site_impact_summary(sites_hit)

    report = generate_report(
        max_height_m, len(vertices_local), lat, lon, jurisdiction,
        analysis_dates, all_shadow_features, sites_affected
    )

    viz = create_visualization(building_gdf, all_shadow_features, sites_gdf, sites_hit, lat, lon)

    return {
        'shadow_polygons': shadow_geojson,
        'sites_affected': sites_affected,
        'summary_report': report,
        'visualization': viz,
    }


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    # Simple box building: 84m × 111m footprint, 244m tall (~800ft)
    # Centered at origin, Z-up
    w, d, h = 42.0, 55.5, 243.84
    test_obj = f"""# Simple box building for testing
v -{w} -{d} 0
v  {w} -{d} 0
v  {w}  {d} 0
v -{w}  {d} 0
v -{w} -{d} {h}
v  {w} -{d} {h}
v  {w}  {d} {h}
v -{w}  {d} {h}
f 1 2 3 4
f 5 6 7 8
f 1 2 6 5
f 2 3 7 6
f 3 4 8 7
f 4 1 5 8
"""
    test_inputs = {
        'building_geojson': {
            'type': 'FeatureCollection',
            'features': [{
                'type': 'Feature',
                'geometry': {
                    'type': 'Polygon',
                    'coordinates': [[
                        [-73.985758, 40.757247],
                        [-73.984882, 40.756879],
                        [-73.984242, 40.757753],
                        [-73.985118, 40.758121],
                        [-73.985758, 40.757247],
                    ]]
                },
                'properties': {}
            }]
        },
        'building_obj': test_obj,
        'model_rotation_deg': 29,
        'jurisdiction': 'NYC',
    }
    result = execute(test_inputs)
    print(result['summary_report'])
    print(f"Shadow features: {len(result['shadow_polygons']['features'])}")
    print(f"Sites affected: {len(result['sites_affected'])}")
