"""
Shadow Tier 3: Shadow Projection Engine

CEQR Technical Manual Chapter 8, Sections 314-325.
Projects accurate 3D building shadows using proper solar position calculations
(pysolar) and UTM coordinate geometry. Works for any lat/lon location.

Core algorithm:
  1. For each analysis datetime, compute solar altitude + azimuth (pysolar)
  2. Transform building footprint to UTM (meter-based CRS)
  3. Project each top vertex of the extruded building to ground plane
  4. Shadow polygon = convex hull of (footprint vertices + projected top vertices)
  5. Transform back to WGS84

CEQR NYC representative days: Dec 21, Mar 21, May 6, Jun 21
Timeframe window: 1.5 hours after sunrise to 1.5 hours before sunset (EST, no DST)
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
from shapely.geometry import (
    MultiPolygon, Point, Polygon, mapping, shape
)
from shapely.ops import unary_union

warnings.filterwarnings('ignore', message="I don't know about leap seconds")

EST = timezone(timedelta(hours=-5))

# CEQR NYC representative analysis days
CEQR_ANALYSIS_DATES = {
    'NYC': ['2024-12-21', '2024-03-21', '2024-05-06', '2024-06-21'],
    'generic': ['2024-12-21', '2024-03-21', '2024-06-21'],
}

# Hourly interval for shadow snapshots (minutes)
ANALYSIS_INTERVAL_MIN = 60


def execute(inputs):
    building_geojson = inputs.get('building_geojson')
    building_height_ft = inputs.get('building_height_ft')
    jurisdiction = inputs.get('jurisdiction', 'NYC')
    sensitive_sites_input = inputs.get('sensitive_sites')
    analysis_dates = inputs.get('analysis_dates')

    if not building_geojson:
        raise ValueError("building_geojson is required")
    if not building_height_ft:
        raise ValueError("building_height_ft is required")

    if isinstance(building_geojson, str):
        building_geojson = json.loads(building_geojson)

    building_gdf = gpd.GeoDataFrame.from_features(building_geojson['features'])
    if building_gdf.crs is None:
        building_gdf.set_crs(epsg=4326, inplace=True)

    building_union = unary_union(building_gdf.geometry)
    centroid = building_union.centroid
    lat, lon = centroid.y, centroid.x

    building_height_m = building_height_ft * 0.3048

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
        else:
            sites_gdf = gpd.GeoDataFrame({'name': [], 'geometry': []}, crs='EPSG:4326')

    # Determine analysis dates
    if not analysis_dates:
        analysis_dates = CEQR_ANALYSIS_DATES.get(jurisdiction, CEQR_ANALYSIS_DATES['generic'])

    # Set up UTM projection for this location
    utm_crs, wgs_to_utm, utm_to_wgs = get_utm_transformers(lon, lat)

    # Project building to UTM
    building_utm = building_gdf.to_crs(utm_crs)
    building_footprint_utm = unary_union(building_utm.geometry)
    footprint_coords_utm = list(building_footprint_utm.exterior.coords)

    # Compute sunrise/sunset for each analysis date and derive time windows
    all_shadow_features = []
    sites_hit = {}  # site_name -> list of hit datetimes

    for date_str in analysis_dates:
        year, month, day = map(int, date_str.split('-'))
        sunrise_est, sunset_est = find_sunrise_sunset(lat, lon, year, month, day)

        if sunrise_est is None:
            continue

        window_start = sunrise_est + timedelta(hours=1.5)
        window_end = sunset_est - timedelta(hours=1.5)

        if window_start >= window_end:
            continue

        # Walk through analysis window at hourly intervals
        current_dt = window_start
        while current_dt <= window_end:
            altitude = get_altitude(lat, lon, current_dt)
            azimuth = get_azimuth(lat, lon, current_dt)

            if altitude > 2.0:  # Skip near-horizon sun (< 2° altitude)
                shadow_polygon_utm = project_shadow_utm(
                    footprint_coords_utm, building_height_m, altitude, azimuth
                )

                if shadow_polygon_utm and shadow_polygon_utm.is_valid:
                    # Convert shadow back to WGS84
                    shadow_wgs = transform_polygon_to_wgs(shadow_polygon_utm, utm_to_wgs)

                    shadow_length_m = building_height_m / math.tan(math.radians(altitude))

                    feature = {
                        'type': 'Feature',
                        'geometry': mapping(shadow_wgs),
                        'properties': {
                            'date': date_str,
                            'time_est': current_dt.strftime('%H:%M'),
                            'datetime_iso': current_dt.isoformat(),
                            'solar_altitude_deg': round(altitude, 2),
                            'solar_azimuth_deg': round(azimuth, 2),
                            'shadow_length_m': round(shadow_length_m, 1),
                        }
                    }
                    all_shadow_features.append(feature)

                    # Check sensitive site intersections
                    for idx, site_row in sites_gdf.iterrows():
                        site_name = site_row.get('signname', site_row.get('propname', site_row.get('name', f'Site {idx}')))
                        if shadow_wgs.intersects(site_row.geometry):
                            if site_name not in sites_hit:
                                sites_hit[site_name] = []
                            sites_hit[site_name].append(current_dt)

            current_dt += timedelta(minutes=ANALYSIS_INTERVAL_MIN)

    shadow_geojson = {
        'type': 'FeatureCollection',
        'features': all_shadow_features
    }

    # Summarize site impacts
    sites_affected = build_site_impact_summary(sites_hit)

    report = generate_report(
        building_height_ft, lat, lon, jurisdiction,
        analysis_dates, all_shadow_features, sites_affected
    )

    viz = create_visualization(
        building_gdf, all_shadow_features, sites_gdf, lat, lon
    )

    return {
        'shadow_polygons': shadow_geojson,
        'sites_affected': sites_affected,
        'summary_report': report,
        'visualization': viz
    }


# ---------------------------------------------------------------------------
# Solar + geometry helpers
# ---------------------------------------------------------------------------

def get_utm_transformers(lon, lat):
    """Return (utm_crs_string, wgs84->utm transformer, utm->wgs84 transformer)."""
    zone = int((lon + 180) / 6) + 1
    hemisphere = 'north' if lat >= 0 else 'south'
    epsg = 32600 + zone if lat >= 0 else 32700 + zone
    utm_crs = f'EPSG:{epsg}'
    wgs_to_utm = Transformer.from_crs('EPSG:4326', utm_crs, always_xy=True)
    utm_to_wgs = Transformer.from_crs(utm_crs, 'EPSG:4326', always_xy=True)
    return utm_crs, wgs_to_utm, utm_to_wgs


def find_sunrise_sunset(lat, lon, year, month, day):
    """
    Scan at 1-minute intervals to find sunrise and sunset in EST.
    Returns (sunrise_datetime_est, sunset_datetime_est) or (None, None).
    """
    sunrise = None
    sunset = None
    prev_above = False

    for hour in range(4, 22):
        for minute in range(0, 60, 1):
            dt = datetime(year, month, day, hour, minute, 0, tzinfo=EST)
            alt = get_altitude(lat, lon, dt)
            above = alt > 0
            if above and not prev_above:
                sunrise = dt
            if not above and prev_above and sunrise is not None:
                sunset = dt
            prev_above = above

    return sunrise, sunset


def project_shadow_utm(footprint_coords_utm, height_m, solar_altitude_deg, solar_azimuth_deg):
    """
    Project shadow polygon in UTM coordinates.

    For each top vertex of the extruded building:
      shadow_pt = vertex + (height / tan(altitude)) in the direction opposite the sun

    Shadow polygon = convex hull of (footprint vertices + projected shadow vertices).
    """
    if solar_altitude_deg <= 0:
        return None

    altitude_rad = math.radians(solar_altitude_deg)
    shadow_length = height_m / math.tan(altitude_rad)

    # Shadow falls opposite to the sun's azimuth
    shadow_az = (solar_azimuth_deg + 180.0) % 360.0
    shadow_az_rad = math.radians(shadow_az)

    # Offset vector in UTM (east = +x, north = +y)
    dx = shadow_length * math.sin(shadow_az_rad)
    dy = shadow_length * math.cos(shadow_az_rad)

    # All points: footprint base + projected top vertices
    all_points = list(footprint_coords_utm)
    for x, y in footprint_coords_utm:
        all_points.append((x + dx, y + dy))

    if len(all_points) < 3:
        return None

    from shapely.geometry import MultiPoint
    return MultiPoint(all_points).convex_hull


def transform_polygon_to_wgs(polygon_utm, utm_to_wgs):
    """Transform a Shapely polygon from UTM to WGS84."""
    if polygon_utm.geom_type == 'Polygon':
        coords = list(polygon_utm.exterior.coords)
        wgs_coords = [utm_to_wgs.transform(x, y) for x, y in coords]
        return Polygon(wgs_coords)
    return polygon_utm


def build_site_impact_summary(sites_hit):
    """Build a list of site impact dicts with enter/exit times per date."""
    summary = []
    for site_name, datetimes in sites_hit.items():
        if not datetimes:
            continue
        datetimes_sorted = sorted(datetimes)

        # Group by date
        by_date = {}
        for dt in datetimes_sorted:
            d = dt.strftime('%Y-%m-%d')
            if d not in by_date:
                by_date[d] = []
            by_date[d].append(dt)

        date_impacts = []
        for date, dts in by_date.items():
            enter = min(dts).strftime('%H:%M EST')
            exit_ = max(dts).strftime('%H:%M EST')
            duration = int((max(dts) - min(dts)).total_seconds() / 60)
            date_impacts.append({
                'date': date,
                'shadow_enter': enter,
                'shadow_exit': exit_,
                'duration_minutes': duration
            })

        summary.append({
            'site_name': site_name,
            'analysis_days_affected': len(by_date),
            'date_impacts': date_impacts
        })
    return summary


# ---------------------------------------------------------------------------
# Report + visualization
# ---------------------------------------------------------------------------

def generate_report(height_ft, lat, lon, jurisdiction, analysis_dates,
                    shadow_features, sites_affected):
    n_shadows = len(shadow_features)
    n_sites = len(sites_affected)

    report = f"""Shadow Tier 3: Screening Assessment Results
============================================

Building Height: {height_ft} ft
Location: {round(lat, 4)}N, {round(lon, 4)}W
Jurisdiction: {jurisdiction}
Analysis Method: CEQR Technical Manual Chapter 8, Sections 314-314.5
Solar Calculator: pysolar (accurate ephemeris)
Shadow Projection: 3D vertex projection with UTM coordinate geometry

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

    if sites_affected:
        report += "CONCLUSION\n"
        report += "----------\n"
        report += f"Shadows from the proposed building reach {n_sites} sensitive site(s).\n"
        report += "A detailed shadow analysis (Tier 3 detailed / Section 320) is warranted\n"
        report += "to document incremental shadow extent and duration for impact determination.\n"
    else:
        report += "CONCLUSION\n"
        report += "----------\n"
        report += "No shadows from the proposed building reach any identified sensitive sites.\n"
        report += "No further shadow analysis is warranted.\n"

    return report


def create_visualization(building_gdf, shadow_features, sites_gdf, lat, lon):
    m = folium.Map(location=[lat, lon], zoom_start=15, tiles='OpenStreetMap')

    # Color palette per analysis date
    date_colors = {}
    palette = ['#ef4444', '#f97316', '#eab308', '#22c55e',
               '#06b6d4', '#6366f1', '#a855f7', '#ec4899']
    unique_dates = sorted(set(f['properties']['date'] for f in shadow_features))
    for i, d in enumerate(unique_dates):
        date_colors[d] = palette[i % len(palette)]

    # Shadow polygons (grouped by date, semi-transparent)
    for date in unique_dates:
        date_features = [f for f in shadow_features if f['properties']['date'] == date]
        color = date_colors[date]
        geojson_layer = {
            'type': 'FeatureCollection',
            'features': date_features
        }
        folium.GeoJson(
            geojson_layer,
            name=f'Shadows {date}',
            style_function=lambda x, c=color: {
                'fillColor': c,
                'color': c,
                'weight': 0.5,
                'fillOpacity': 0.2
            },
            tooltip=folium.GeoJsonTooltip(
                fields=['time_est', 'solar_altitude_deg', 'shadow_length_m'],
                aliases=['Time (EST):', 'Solar Altitude:', 'Shadow Length (m):']
            )
        ).add_to(m)

    # Building footprint
    folium.GeoJson(
        building_gdf,
        name='Proposed Building',
        style_function=lambda x: {
            'fillColor': '#3b82f6',
            'color': '#1d4ed8',
            'weight': 2,
            'fillOpacity': 0.8
        },
        tooltip='Proposed Building'
    ).add_to(m)

    # Sensitive sites
    for idx, row in sites_gdf.iterrows():
        geom = row.geometry
        name = row.get('signname', row.get('propname', row.get('name', f'Site {idx}')))
        if geom.geom_type == 'Point':
            folium.CircleMarker(
                location=[geom.y, geom.x],
                radius=7,
                color='#7c3aed',
                fill=True,
                fill_color='#a78bfa',
                fill_opacity=0.8,
                tooltip=name
            ).add_to(m)
        else:
            folium.GeoJson(
                mapping(geom),
                style_function=lambda x: {
                    'fillColor': '#a78bfa', 'color': '#7c3aed',
                    'weight': 2, 'fillOpacity': 0.4
                },
                tooltip=name
            ).add_to(m)

    folium.LayerControl().add_to(m)
    return m._repr_html_()


if __name__ == '__main__':
    test_inputs = {
        'building_geojson': {
            'type': 'FeatureCollection',
            'features': [{
                'type': 'Feature',
                'geometry': {
                    'type': 'Polygon',
                    'coordinates': [[
                        [-73.9855, 40.7580],
                        [-73.9845, 40.7580],
                        [-73.9845, 40.7570],
                        [-73.9855, 40.7570],
                        [-73.9855, 40.7580]
                    ]]
                },
                'properties': {}
            }]
        },
        'building_height_ft': 400,
        'jurisdiction': 'NYC'
    }
    result = execute(test_inputs)
    print(result['summary_report'])
    print(f"Shadow features generated: {len(result['shadow_polygons']['features'])}")
