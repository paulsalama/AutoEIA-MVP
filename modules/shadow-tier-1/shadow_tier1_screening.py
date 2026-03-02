"""
Shadow Tier 1 Preliminary Screening Module

Performs initial geospatial proximity analysis to determine if detailed shadow study is warranted.
Based on AutoEIA-building_proximity prototype.
"""
import json
import geopandas as gpd
from shapely.geometry import shape, mapping
from pathlib import Path
import folium


def execute(inputs):
    """
    Execute Shadow Tier 1 screening analysis

    Args:
        inputs (dict): Dictionary containing:
            - building_geojson: GeoJSON of building footprint
            - building_height_ft: Building height in feet
            - sensitive_sites (optional): GeoJSON of sensitive sites
            - buffer_multiplier (optional): Multiplier for shadow radius (default: 4.0)

    Returns:
        dict: Analysis results with triggered flag, affected sites, and visualizations
    """
    # Parse inputs
    building_geojson = inputs.get('building_geojson')
    building_height_ft = inputs.get('building_height_ft')
    sensitive_sites_geojson = inputs.get('sensitive_sites')
    buffer_multiplier = inputs.get('buffer_multiplier', 4.3)

    # Validate inputs
    if not building_geojson:
        raise ValueError("building_geojson is required")
    if not building_height_ft:
        raise ValueError("building_height_ft is required")

    # Convert building to GeoDataFrame
    if isinstance(building_geojson, str):
        building_geojson = json.loads(building_geojson)

    building_gdf = gpd.GeoDataFrame.from_features(building_geojson['features'])
    if building_gdf.crs is None:
        building_gdf.set_crs(epsg=4326, inplace=True)

    # Calculate shadow buffer radius (building height * multiplier)
    # Convert to meters for buffer calculation (1 foot ≈ 0.3048 meters)
    shadow_radius_m = building_height_ft * 0.3048 * buffer_multiplier

    # Project to appropriate CRS for buffer calculation (Web Mercator)
    building_projected = building_gdf.to_crs(epsg=3857)

    # Create buffer
    shadow_buffer = building_projected.buffer(shadow_radius_m)

    # Convert buffer back to WGS84 for output
    buffer_gdf = gpd.GeoDataFrame(geometry=shadow_buffer, crs='EPSG:3857')
    buffer_gdf = buffer_gdf.to_crs(epsg=4326)

    # Load or use provided sensitive sites
    if sensitive_sites_geojson:
        if isinstance(sensitive_sites_geojson, str):
            sensitive_sites_geojson = json.loads(sensitive_sites_geojson)
        sites_gdf = gpd.GeoDataFrame.from_features(sensitive_sites_geojson['features'])
        if sites_gdf.crs is None:
            sites_gdf.set_crs(epsg=4326, inplace=True)
    else:
        # Use default NYC dataset if available
        default_sites_path = Path(__file__).parent.parent.parent / 'datasets' / 'nyc_dpr_parks_properties.geojson'
        if default_sites_path.exists():
            sites_gdf = gpd.read_file(default_sites_path)
            # Convert datetime columns to strings (avoids JSON serialization errors)
            for col in sites_gdf.select_dtypes(include=['datetime64']).columns:
                sites_gdf[col] = sites_gdf[col].astype(str)
        else:
            # Create empty GeoDataFrame if no sites available
            sites_gdf = gpd.GeoDataFrame(columns=['geometry'], crs='EPSG:4326')

    # Find intersecting sites
    if not sites_gdf.empty:
        affected_sites = gpd.sjoin(sites_gdf, buffer_gdf, how='inner', predicate='intersects')
        affected_count = len(affected_sites)
        triggered = affected_count > 0
    else:
        affected_sites = sites_gdf
        affected_count = 0
        triggered = False

    # Generate summary report
    summary_report = f"""Shadow Tier 1 Preliminary Screening Results
============================================

Building Height: {building_height_ft} feet
Shadow Radius: {building_height_ft * buffer_multiplier:,.0f} ft ({shadow_radius_m:,.0f} m)
Buffer Multiplier: {buffer_multiplier}x

Sensitive Sites Within Shadow Radius: {affected_count}

Tier 2 Analysis Triggered: {'YES' if triggered else 'NO'}

"""

    if triggered:
        summary_report += "Recommendation: Proceed with Tier 2 detailed shadow analysis.\n"
        summary_report += f"\nSites within shadow radius:\n"
        unique_names = []
        seen = set()
        for idx, site in affected_sites.iterrows():
            site_name = site.get('signname', site.get('propname', site.get('name', f'Site {idx}')))
            if site_name not in seen:
                seen.add(site_name)
                unique_names.append(site_name)
        for name in unique_names[:15]:
            summary_report += f"  - {name}\n"
        if len(unique_names) > 15:
            summary_report += f"  ... and {len(unique_names) - 15} more\n"
    else:
        summary_report += "Recommendation: No further shadow analysis required.\n"

    # Create visualization
    visualization_html = create_visualization(
        building_gdf,
        buffer_gdf,
        sites_gdf,
        affected_sites,
        building_height_ft,
        shadow_radius_m
    )

    # Prepare outputs
    outputs = {
        'triggered': triggered,
        'affected_sites_count': affected_count,
        'shadow_buffer': json.loads(buffer_gdf.to_json()),
        'summary_report': summary_report,
        'visualization': visualization_html
    }

    # Add affected sites if any
    if not affected_sites.empty:
        # Remove join column if present
        if 'index_right' in affected_sites.columns:
            affected_sites = affected_sites.drop(columns=['index_right'])
        outputs['affected_sites'] = json.loads(affected_sites.to_json())
    else:
        outputs['affected_sites'] = {'type': 'FeatureCollection', 'features': []}

    return outputs


def create_visualization(building_gdf, buffer_gdf, sites_gdf, affected_sites, height_ft, radius_m):
    """Create an interactive Folium map visualization"""

    # Calculate center point
    center = building_gdf.geometry.centroid.iloc[0]
    center_lat, center_lon = center.y, center.x

    # Create map
    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=15,
        tiles='CartoDB positron'
    )

    # Add building footprint
    folium.GeoJson(
        building_gdf,
        name='Building',
        style_function=lambda x: {
            'fillColor': '#3388ff',
            'color': '#3388ff',
            'weight': 2,
            'fillOpacity': 0.6
        },
        tooltip=f'Proposed Building ({height_ft} ft)'
    ).add_to(m)

    # Add shadow buffer
    folium.GeoJson(
        buffer_gdf,
        name='Shadow Radius',
        style_function=lambda x: {
            'fillColor': '#ff7800',
            'color': '#ff7800',
            'weight': 2,
            'fillOpacity': 0.2
        },
        tooltip=f'Shadow Buffer ({radius_m:.1f}m radius)'
    ).add_to(m)

    # Add all sensitive sites (name tooltip)
    if not sites_gdf.empty:
        # Only pass geometry + signname to Folium to keep it lightweight
        sites_display = sites_gdf[['signname', 'geometry']] if 'signname' in sites_gdf.columns else sites_gdf[['geometry']]
        folium.GeoJson(
            sites_display,
            name='Sensitive Sites',
            style_function=lambda x: {
                'fillColor': '#90ee90',
                'color': '#228b22',
                'weight': 1,
                'fillOpacity': 0.4
            },
            tooltip=folium.GeoJsonTooltip(
                fields=['signname'] if 'signname' in sites_display.columns else [],
                aliases=['Park:'] if 'signname' in sites_display.columns else [],
                sticky=False
            )
        ).add_to(m)

    # Highlight affected sites with park name tooltip
    if not affected_sites.empty:
        affected_geojson = json.loads(affected_sites.to_json())
        # Determine which name field is available
        name_field = next(
            (f for f in ['signname', 'propname', 'name']
             if affected_geojson['features'] and f in affected_geojson['features'][0].get('properties', {})),
            None
        )
        folium.GeoJson(
            affected_geojson,
            name='Affected Sites',
            style_function=lambda x: {
                'fillColor': '#ff0000',
                'color': '#8b0000',
                'weight': 2,
                'fillOpacity': 0.6
            },
            tooltip=folium.GeoJsonTooltip(
                fields=[name_field] if name_field else [],
                aliases=['Affected:'] if name_field else [],
                sticky=False
            ) if name_field else 'Affected Site'
        ).add_to(m)

    # Add layer control
    folium.LayerControl().add_to(m)

    # Return HTML
    return m._repr_html_()


# For testing
if __name__ == '__main__':
    # Sample test data
    test_inputs = {
        'building_geojson': {
            'type': 'FeatureCollection',
            'features': [{
                'type': 'Feature',
                'geometry': {
                    'type': 'Polygon',
                    'coordinates': [[
                        [-73.9851, 40.7589],
                        [-73.9841, 40.7589],
                        [-73.9841, 40.7579],
                        [-73.9851, 40.7579],
                        [-73.9851, 40.7589]
                    ]]
                },
                'properties': {}
            }]
        },
        'building_height_ft': 200,
        'buffer_multiplier': 4.0
    }

    result = execute(test_inputs)
    print(result['summary_report'])
    print(f"Triggered: {result['triggered']}")
    print(f"Affected sites: {result['affected_sites_count']}")
