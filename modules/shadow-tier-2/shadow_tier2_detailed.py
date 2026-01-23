"""
Shadow Tier 2 Detailed Analysis Module

Performs detailed shadow path calculations for specified dates and times.
Based on UT_Hackathon prototype.
"""
import json
import math
import pytz
from datetime import datetime, timedelta
import geopandas as gpd
from shapely.geometry import Polygon, shape, mapping
from shapely.affinity import translate, rotate
import folium
import numpy as np


def execute(inputs):
    """
    Execute Shadow Tier 2 detailed analysis

    Args:
        inputs (dict): Dictionary containing:
            - building_geojson: GeoJSON of building footprint
            - building_height_ft: Building height in feet
            - analysis_dates: List of dates (YYYY-MM-DD)
            - time_points (optional): List of times (HH:MM)
            - jurisdiction (optional): NYC, Boston, or generic
            - latitude (optional): Latitude for calculations
            - longitude (optional): Longitude for calculations

    Returns:
        dict: Analysis results with shadow geometries and visualizations
    """
    # Parse inputs
    building_geojson = inputs.get('building_geojson')
    building_height_ft = inputs.get('building_height_ft')
    analysis_dates = inputs.get('analysis_dates', [])
    time_points = inputs.get('time_points')
    jurisdiction = inputs.get('jurisdiction', 'generic')
    lat = inputs.get('latitude')
    lon = inputs.get('longitude')

    # Validate inputs
    if not building_geojson:
        raise ValueError("building_geojson is required")
    if not building_height_ft:
        raise ValueError("building_height_ft is required")
    if not analysis_dates:
        raise ValueError("analysis_dates is required")

    # Convert building to GeoDataFrame
    if isinstance(building_geojson, str):
        building_geojson = json.loads(building_geojson)

    building_gdf = gpd.GeoDataFrame.from_features(building_geojson['features'])
    if building_gdf.crs is None:
        building_gdf.set_crs(epsg=4326, inplace=True)

    # Get centroid for solar calculations if lat/lon not provided
    centroid = building_gdf.geometry.centroid.iloc[0]
    if lat is None:
        lat = centroid.y
    if lon is None:
        lon = centroid.x

    # Set default time points based on jurisdiction
    if not time_points:
        time_points = get_default_time_points(jurisdiction)

    # Generate all datetime combinations
    analysis_datetimes = []
    for date_str in analysis_dates:
        for time_str in time_points:
            dt_str = f"{date_str} {time_str}"
            dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
            # Assume local timezone (could be enhanced to use jurisdiction timezone)
            analysis_datetimes.append(dt)

    # Calculate shadows for each datetime
    shadow_features = []
    total_area_sqft = 0
    max_shadow_length = 0
    max_shadow_time = None

    for dt in analysis_datetimes:
        # Calculate solar position
        solar_altitude, solar_azimuth = calculate_solar_position(lat, lon, dt)

        # Skip if sun is below horizon
        if solar_altitude <= 0:
            continue

        # Calculate shadow
        shadow_geom = calculate_shadow_polygon(
            building_gdf.geometry.iloc[0],
            building_height_ft,
            solar_altitude,
            solar_azimuth
        )

        if shadow_geom:
            # Calculate shadow area (project to UTM for accurate area)
            shadow_gdf_temp = gpd.GeoDataFrame(geometry=[shadow_geom], crs='EPSG:4326')
            shadow_projected = shadow_gdf_temp.to_crs(epsg=3857)
            area_sqm = shadow_projected.geometry.area.iloc[0]
            area_sqft = area_sqm * 10.764  # Convert to square feet

            # Calculate shadow length
            building_centroid = building_gdf.geometry.centroid.iloc[0]
            shadow_centroid = shadow_geom.centroid
            # Approximate distance
            distance = math.sqrt(
                (shadow_centroid.x - building_centroid.x)**2 +
                (shadow_centroid.y - building_centroid.y)**2
            ) * 111000  # Rough conversion to meters

            if distance > max_shadow_length:
                max_shadow_length = distance
                max_shadow_time = dt

            shadow_features.append({
                'type': 'Feature',
                'geometry': mapping(shadow_geom),
                'properties': {
                    'datetime': dt.isoformat(),
                    'date': dt.strftime('%Y-%m-%d'),
                    'time': dt.strftime('%H:%M'),
                    'solar_altitude': round(solar_altitude, 2),
                    'solar_azimuth': round(solar_azimuth, 2),
                    'area_sqft': round(area_sqft, 2),
                    'shadow_length_m': round(distance, 2)
                }
            })

            total_area_sqft += area_sqft

    # Create shadow GeoJSON
    shadow_geojson = {
        'type': 'FeatureCollection',
        'features': shadow_features
    }

    # Generate analysis summary
    analysis_summary = {
        'total_shadows_calculated': len(shadow_features),
        'dates_analyzed': len(analysis_dates),
        'time_points_per_date': len(time_points),
        'max_shadow_length_m': round(max_shadow_length, 2) if max_shadow_length > 0 else 0,
        'max_shadow_time': max_shadow_time.isoformat() if max_shadow_time else None,
        'total_area_sqft': round(total_area_sqft, 2),
        'average_area_sqft': round(total_area_sqft / len(shadow_features), 2) if shadow_features else 0
    }

    # Generate summary report
    summary_report = generate_summary_report(
        building_height_ft,
        analysis_dates,
        time_points,
        jurisdiction,
        analysis_summary,
        shadow_features
    )

    # Create visualization
    visualization_html = create_visualization(
        building_gdf,
        shadow_geojson,
        lat,
        lon
    )

    # Prepare outputs
    outputs = {
        'shadow_geometries': shadow_geojson,
        'affected_area_sqft': analysis_summary['total_area_sqft'],
        'analysis_summary': analysis_summary,
        'summary_report': summary_report,
        'visualization': visualization_html
    }

    return outputs


def get_default_time_points(jurisdiction):
    """Get default time points based on jurisdiction"""
    if jurisdiction == 'NYC':
        # NYC: Specific analysis windows
        return ['09:00', '10:00', '11:00', '12:00', '13:00', '14:00', '15:00']
    elif jurisdiction == 'Boston':
        # Boston: Hourly from sunrise to sunset (simplified)
        return ['08:00', '09:00', '10:00', '11:00', '12:00', '13:00', '14:00', '15:00', '16:00', '17:00']
    else:
        # Generic: Key times
        return ['09:00', '12:00', '15:00']


def calculate_solar_position(latitude, longitude, dt):
    """
    Calculate solar altitude and azimuth for a given location and time
    Simplified calculation - production version should use pysolar or pvlib
    """
    # This is a simplified calculation
    # For production, use: from pysolar import solar
    # solar_altitude = solar.get_altitude(latitude, longitude, dt)
    # solar_azimuth = solar.get_azimuth(latitude, longitude, dt)

    # Simplified calculation for demonstration
    day_of_year = dt.timetuple().tm_yday
    hour = dt.hour + dt.minute / 60.0

    # Solar declination (simplified)
    declination = 23.45 * math.sin(math.radians((360/365) * (day_of_year - 81)))

    # Hour angle
    hour_angle = 15 * (hour - 12)

    # Solar altitude (simplified)
    lat_rad = math.radians(latitude)
    dec_rad = math.radians(declination)
    ha_rad = math.radians(hour_angle)

    altitude = math.asin(
        math.sin(lat_rad) * math.sin(dec_rad) +
        math.cos(lat_rad) * math.cos(dec_rad) * math.cos(ha_rad)
    )
    altitude_deg = math.degrees(altitude)

    # Solar azimuth (simplified - measured from north, clockwise)
    azimuth = math.atan2(
        math.sin(ha_rad),
        math.cos(ha_rad) * math.sin(lat_rad) - math.tan(dec_rad) * math.cos(lat_rad)
    )
    azimuth_deg = math.degrees(azimuth) + 180  # Convert to 0-360

    return altitude_deg, azimuth_deg


def calculate_shadow_polygon(building_geom, height_ft, solar_altitude, solar_azimuth):
    """
    Calculate shadow polygon for a building at given solar position
    """
    if solar_altitude <= 0:
        return None

    # Calculate shadow length
    height_m = height_ft * 0.3048
    shadow_length_m = height_m / math.tan(math.radians(solar_altitude))

    # Convert to approximate degrees (rough conversion)
    shadow_length_deg = shadow_length_m / 111000

    # Get building bounds
    if building_geom.geom_type == 'Polygon':
        building_coords = list(building_geom.exterior.coords)
    else:
        return None

    # Project shadow in opposite direction of sun azimuth
    shadow_direction = (solar_azimuth + 180) % 360

    # Calculate shadow offset
    dx = shadow_length_deg * math.sin(math.radians(shadow_direction))
    dy = shadow_length_deg * math.cos(math.radians(shadow_direction))

    # Create shadow polygon by translating building polygon
    shadow_coords = [(x + dx, y + dy) for x, y in building_coords]

    # Combine building and shadow to create full shadow polygon
    all_coords = list(building_coords) + list(reversed(shadow_coords))

    try:
        shadow_polygon = Polygon(all_coords)
        if shadow_polygon.is_valid:
            return shadow_polygon
        else:
            return shadow_polygon.buffer(0)  # Fix invalid polygons
    except:
        return None


def generate_summary_report(height_ft, dates, times, jurisdiction, summary, shadows):
    """Generate text summary report"""
    report = f"""Shadow Tier 2 Detailed Analysis Results
========================================

Building Height: {height_ft} feet
Jurisdiction: {jurisdiction.upper()}
Analysis Dates: {', '.join(dates)}
Time Points: {', '.join(times)}

ANALYSIS SUMMARY
----------------
Total Shadow Calculations: {summary['total_shadows_calculated']}
Maximum Shadow Length: {summary['max_shadow_length_m']:.1f} meters
Time of Maximum Shadow: {summary['max_shadow_time'] or 'N/A'}
Total Shadow Area: {summary['total_area_sqft']:,.1f} square feet
Average Shadow Area: {summary['average_area_sqft']:,.1f} square feet

SHADOW DETAILS
--------------
"""

    for i, shadow in enumerate(shadows[:10], 1):  # Show first 10
        props = shadow['properties']
        report += f"\n{i}. {props['date']} at {props['time']}\n"
        report += f"   Solar Altitude: {props['solar_altitude']}°, Azimuth: {props['solar_azimuth']}°\n"
        report += f"   Shadow Area: {props['area_sqft']:,.1f} sq ft, Length: {props['shadow_length_m']:.1f} m\n"

    if len(shadows) > 10:
        report += f"\n... and {len(shadows) - 10} more shadow calculations\n"

    report += "\n\nRECOMMENDATIONS\n"
    report += "---------------\n"
    report += "Review the interactive visualization to assess shadow impacts on sensitive sites.\n"
    report += "Consider Tier 3 comprehensive analysis if significant impacts are identified.\n"

    return report


def create_visualization(building_gdf, shadow_geojson, lat, lon):
    """Create interactive Folium map with shadow animations"""

    # Create map centered on building
    m = folium.Map(
        location=[lat, lon],
        zoom_start=16,
        tiles='OpenStreetMap'
    )

    # Add building
    folium.GeoJson(
        building_gdf,
        name='Building',
        style_function=lambda x: {
            'fillColor': '#3388ff',
            'color': '#0000ff',
            'weight': 3,
            'fillOpacity': 0.7
        },
        tooltip='Proposed Building'
    ).add_to(m)

    # Add shadows with different colors for different times
    if shadow_geojson['features']:
        # Group by date
        shadows_by_date = {}
        for feature in shadow_geojson['features']:
            date = feature['properties']['date']
            if date not in shadows_by_date:
                shadows_by_date[date] = []
            shadows_by_date[date].append(feature)

        # Color scheme
        colors = ['#ff0000', '#ff7f00', '#ffff00', '#00ff00', '#0000ff', '#4b0082', '#9400d3']

        for idx, (date, shadows) in enumerate(shadows_by_date.items()):
            color = colors[idx % len(colors)]
            date_geojson = {'type': 'FeatureCollection', 'features': shadows}

            folium.GeoJson(
                date_geojson,
                name=f'Shadows - {date}',
                style_function=lambda x, c=color: {
                    'fillColor': c,
                    'color': c,
                    'weight': 1,
                    'fillOpacity': 0.3
                },
                tooltip=folium.GeoJsonTooltip(
                    fields=['time', 'solar_altitude', 'area_sqft'],
                    aliases=['Time:', 'Solar Altitude:', 'Area (sq ft):'],
                    localize=True
                )
            ).add_to(m)

    # Add layer control
    folium.LayerControl().add_to(m)

    return m._repr_html_()


# For testing
if __name__ == '__main__':
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
        'analysis_dates': ['2024-06-21', '2024-12-21'],  # Summer and winter solstice
        'jurisdiction': 'NYC'
    }

    result = execute(test_inputs)
    print(result['summary_report'])
