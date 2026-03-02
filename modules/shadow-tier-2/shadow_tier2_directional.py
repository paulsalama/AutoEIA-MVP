"""
Shadow Tier 2: Directional Screening Module

CEQR Technical Manual Chapter 8, Section 313.
Eliminates sensitive resources that lie in the triangular zone south of the
project site that cannot receive shadow (between ±108° from true north).
Resources in the remaining arc proceed to Tier 3 analysis.
"""
import json
import math
from pathlib import Path
import geopandas as gpd
import folium
from shapely.geometry import Polygon, Point, mapping, shape
from shapely.ops import unary_union


# CEQR: no shadow can fall between -108° and +108° from true north
# (i.e., the arc spanning south, ESE to WSW)
NO_SHADOW_HALF_ANGLE_DEG = 108.0

# Zone polygon extends this far (degrees) — well beyond any realistic Tier 1 buffer
NO_SHADOW_ZONE_RADIUS_DEG = 0.15  # ~12 km


def execute(inputs):
    building_geojson = inputs.get('building_geojson')
    building_height_ft = inputs.get('building_height_ft')
    jurisdiction = inputs.get('jurisdiction', 'NYC')

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

    # Resolve the Tier 1 shadow buffer (for visualization + standalone site filtering)
    shadow_radius_m = building_height_ft * 0.3048 * 4.3
    shadow_buffer_input = inputs.get('shadow_buffer')
    if shadow_buffer_input:
        if isinstance(shadow_buffer_input, str):
            shadow_buffer_input = json.loads(shadow_buffer_input)
        buf_gdf = gpd.GeoDataFrame.from_features(shadow_buffer_input['features'])
        if buf_gdf.crs is None:
            buf_gdf.set_crs(epsg=4326, inplace=True)
    else:
        building_proj = building_gdf.to_crs(epsg=3857)
        buf_gdf = gpd.GeoDataFrame(geometry=building_proj.buffer(shadow_radius_m), crs='EPSG:3857').to_crs(epsg=4326)
    shadow_buffer_geom = unary_union(buf_gdf.geometry)

    # Load sensitive sites — prefer passed-in data, then Tier 1 affected_sites, then filter default dataset
    sensitive_sites_input = inputs.get('sensitive_sites') or inputs.get('affected_sites')

    if sensitive_sites_input:
        if isinstance(sensitive_sites_input, str):
            sensitive_sites_input = json.loads(sensitive_sites_input)
        sites_gdf = gpd.GeoDataFrame.from_features(sensitive_sites_input['features'])
        if sites_gdf.crs is None:
            sites_gdf.set_crs(epsg=4326, inplace=True)
    else:
        # No upstream data — load default dataset and filter to buffer extent
        default_path = Path(__file__).parent.parent.parent / 'datasets' / 'nyc_dpr_parks_properties.geojson'
        if default_path.exists():
            sites_gdf = gpd.read_file(str(default_path))
            for col in sites_gdf.select_dtypes(include=['datetime64']).columns:
                sites_gdf[col] = sites_gdf[col].astype(str)
            sites_gdf = gpd.sjoin(sites_gdf, buf_gdf, how='inner', predicate='intersects')
            if 'index_right' in sites_gdf.columns:
                sites_gdf = sites_gdf.drop(columns=['index_right'])
        else:
            sites_gdf = gpd.GeoDataFrame(
                {'name': [], 'geometry': []}, crs='EPSG:4326'
            )

    # Build the no-shadow zone polygon
    no_shadow_polygon = build_no_shadow_zone(building_union, jurisdiction)

    # Classify each sensitive site
    eliminated = []
    requiring_tier3 = []

    for idx, row in sites_gdf.iterrows():
        geom = row.geometry
        name = row.get('signname', row.get('propname', row.get('name', f'Site {idx + 1}')))

        # A site is eliminated only if it lies ENTIRELY within the no-shadow zone
        if no_shadow_polygon.contains(geom):
            eliminated.append(row)
        else:
            requiring_tier3.append(row)

    # Build output GeoJSON collections (keep only essential fields to limit response size)
    KEEP_PROPS = {'signname', 'propname', 'name', 'typecategory', 'borough', 'acres'}

    def rows_to_geojson(rows):
        features = []
        for row in rows:
            feat = {
                'type': 'Feature',
                'geometry': mapping(row.geometry),
                'properties': {
                    k: str(v) if v is not None else None
                    for k, v in row.items()
                    if k in KEEP_PROPS
                }
            }
            features.append(feat)
        return {'type': 'FeatureCollection', 'features': features}

    sites_eliminated_geojson = rows_to_geojson(eliminated)
    sites_tier3_geojson = rows_to_geojson(requiring_tier3)
    no_shadow_zone_geojson = {
        'type': 'FeatureCollection',
        'features': [{
            'type': 'Feature',
            'geometry': mapping(no_shadow_polygon),
            'properties': {'name': 'No-shadow zone (±108° from north)'}
        }]
    }

    triggered = len(requiring_tier3) > 0

    report = generate_report(
        building_height_ft, jurisdiction,
        eliminated, requiring_tier3, triggered
    )

    centroid = building_union.centroid
    viz = create_visualization(
        building_gdf, no_shadow_polygon, shadow_buffer_geom,
        eliminated, requiring_tier3,
        centroid.y, centroid.x
    )

    return {
        'sites_requiring_tier3': sites_tier3_geojson,
        'sites_eliminated': sites_eliminated_geojson,
        'no_shadow_zone': no_shadow_zone_geojson,
        'triggered': triggered,
        'summary_report': report,
        'visualization': viz
    }


def build_no_shadow_zone(building_geom, jurisdiction):
    """
    Build the triangular no-shadow zone south of the building.
    CEQR (NYC): zone spans azimuths 108° to 252° (clockwise through south).
    Origin: southernmost point of the building footprint.
    """
    half_angle = NO_SHADOW_HALF_ANGLE_DEG
    r = NO_SHADOW_ZONE_RADIUS_DEG

    # Southernmost point of the building
    bounds = building_geom.bounds  # (minx, miny, maxx, maxy)
    # Use the midpoint of the southern edge as the apex
    south_x = (bounds[0] + bounds[2]) / 2
    south_y = bounds[1]
    apex = (south_x, south_y)

    # The no-shadow zone covers azimuths from (180 - half_angle) to (180 + half_angle)
    # i.e., from 72° to 288° ... wait, that's too wide.
    # CEQR says the zone that CANNOT be shaded is between -108° and +108° from north.
    # -108° from north = 252° (WSW)
    # +108° from north = 108° (ESE)
    # So the no-shadow zone sweeps from 108° through 180° (south) to 252°.
    az_start = 180 - half_angle   # 72°? No...
    # Let me be explicit:
    # The no-shadow zone is the area BETWEEN azimuth 108° and 252° (going clockwise through south/180°)
    az_cw_start = 108.0   # ESE
    az_cw_end = 252.0     # WSW

    # Generate arc points
    arc_points = []
    az = az_cw_start
    step = 2.0
    while az <= az_cw_end + 0.01:
        az_rad = math.radians(az)
        px = south_x + r * math.sin(az_rad)
        py = south_y + r * math.cos(az_rad)
        arc_points.append((px, py))
        az += step

    # Close the polygon back to apex
    polygon_coords = [apex] + arc_points + [apex]
    return Polygon(polygon_coords)


def generate_report(height_ft, jurisdiction, eliminated, requiring_tier3, triggered):
    n_elim = len(eliminated)
    n_tier3 = len(requiring_tier3)
    total = n_elim + n_tier3

    elim_names = [r.get('signname', r.get('propname', r.get('name', 'Unknown'))) for r in eliminated]
    tier3_names = [r.get('signname', r.get('propname', r.get('name', 'Unknown'))) for r in requiring_tier3]

    report = f"""Shadow Tier 2: Directional Screening Results
=============================================

Jurisdiction: {jurisdiction}
Building Height: {height_ft} ft
Analysis Method: CEQR Technical Manual Chapter 8, Section 313
No-Shadow Zone: ±108° from true north (azimuths 108°–252°)

SCREENING SUMMARY
-----------------
Total sensitive sites evaluated: {total}
Sites eliminated (in no-shadow zone): {n_elim}
Sites requiring Tier 3 analysis: {n_tier3}
Tier 3 triggered: {'YES' if triggered else 'NO'}

"""
    if elim_names:
        report += "ELIMINATED SITES (south of building — cannot receive shadow)\n"
        report += "-" * 60 + "\n"
        for name in elim_names[:10]:
            report += f"  [OK] {name}\n"
        if len(elim_names) > 10:
            report += f"  ... and {len(elim_names) - 10} more\n"
        report += "\n"

    if tier3_names:
        report += "SITES REQUIRING TIER 3 ANALYSIS\n"
        report += "-" * 60 + "\n"
        for name in tier3_names[:10]:
            report += f"  -> {name}\n"
        if len(tier3_names) > 10:
            report += f"  ... and {len(tier3_names) - 10} more\n"
        report += "\n"

    if triggered:
        report += "CONCLUSION\n"
        report += "----------\n"
        report += f"{n_tier3} sensitive site(s) lie within the area that could potentially\n"
        report += "receive shadow from the proposed building. Proceed to Tier 3\n"
        report += "screening assessment to determine if shadows would actually reach\n"
        report += "these resources.\n"
    else:
        report += "CONCLUSION\n"
        report += "----------\n"
        report += "All sensitive sites lie within the no-shadow zone south of the\n"
        report += "proposed building. No further shadow analysis is warranted.\n"

    return report


def create_visualization(building_gdf, no_shadow_polygon, shadow_buffer_geom, eliminated, requiring_tier3, lat, lon):
    m = folium.Map(location=[lat, lon], zoom_start=15, tiles='CartoDB positron')

    # Shadow buffer circle (Tier 1 radius — dashed orange outline, no fill)
    if shadow_buffer_geom:
        folium.GeoJson(
            mapping(shadow_buffer_geom),
            name='Tier 1 shadow buffer',
            style_function=lambda x: {
                'fillColor': '#ff7800',
                'color': '#ff7800',
                'weight': 2,
                'fillOpacity': 0.08,
                'dashArray': '6 4'
            },
            tooltip='Tier 1 shadow buffer (4.3× building height)'
        ).add_to(m)

    # No-shadow zone (light yellow wedge)
    folium.GeoJson(
        mapping(no_shadow_polygon),
        name='No-shadow zone (±108°)',
        style_function=lambda x: {
            'fillColor': '#fef9c3',
            'color': '#ca8a04',
            'weight': 2,
            'fillOpacity': 0.35,
            'dashArray': '6 4'
        },
        tooltip='No-shadow zone: sites here cannot receive shadow'
    ).add_to(m)

    # Building footprint
    folium.GeoJson(
        building_gdf,
        name='Proposed Building',
        style_function=lambda x: {
            'fillColor': '#3b82f6',
            'color': '#1d4ed8',
            'weight': 2,
            'fillOpacity': 0.7
        },
        tooltip='Proposed Building'
    ).add_to(m)

    # Eliminated sites — single batched layer (green)
    if eliminated:
        elim_fc = {
            'type': 'FeatureCollection',
            'features': [
                {'type': 'Feature', 'geometry': mapping(r.geometry),
                 'properties': {'name': r.get('signname', r.get('propname', r.get('name', 'Site')))}}
                for r in eliminated
            ]
        }
        folium.GeoJson(
            elim_fc,
            name='Eliminated (south of building)',
            style_function=lambda x: {
                'fillColor': '#22c55e', 'color': '#16a34a',
                'weight': 1, 'fillOpacity': 0.4
            },
            tooltip=folium.GeoJsonTooltip(fields=['name'], aliases=['✓ Eliminated:'], sticky=False)
        ).add_to(m)

    # Sites requiring Tier 3 — single batched layer (red)
    if requiring_tier3:
        tier3_fc = {
            'type': 'FeatureCollection',
            'features': [
                {'type': 'Feature', 'geometry': mapping(r.geometry),
                 'properties': {'name': r.get('signname', r.get('propname', r.get('name', 'Site')))}}
                for r in requiring_tier3
            ]
        }
        folium.GeoJson(
            tier3_fc,
            name='Requires Tier 3 analysis',
            style_function=lambda x: {
                'fillColor': '#f87171', 'color': '#dc2626',
                'weight': 1, 'fillOpacity': 0.4
            },
            tooltip=folium.GeoJsonTooltip(fields=['name'], aliases=['→ Tier 3:'], sticky=False)
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
    print('Triggered:', result['triggered'])
