# AutoEIA Datasets

This folder contains sample GeoJSON datasets for testing and demonstration purposes.

## Building Footprints

Example building footprints for shadow analysis testing:

### 1. `example_building_midtown.geojson`
- **Location**: Near Times Square, Midtown Manhattan
- **Suggested Height**: 200 feet
- **Footprint Area**: ~43,560 sq ft (1 acre)
- **Use Case**: Medium-sized commercial building, typical shadow analysis

### 2. `example_building_small.geojson`
- **Location**: Near Central Park, Midtown Manhattan
- **Suggested Height**: 60 feet
- **Footprint Area**: ~10,890 sq ft
- **Use Case**: Small commercial building, minimal shadow impact

### 3. `example_building_tall.geojson`
- **Location**: Near Bryant Park, Midtown Manhattan
- **Suggested Height**: 800 feet (~60 stories)
- **Footprint Area**: ~43,560 sq ft (1 acre)
- **Use Case**: High-rise tower, significant shadow impact testing

## Sensitive Sites

### `nyc_sensitive_sites.geojson`
Sample sensitive sites in NYC that may be affected by shadows:
- **Central Park - South Section**: Large park polygon
- **Bryant Park**: Medium park polygon
- **Playground**: Point feature representing a playground

## Usage

### In the AutoEIA Platform:

1. **Shadow Tier 1 Module**:
   - Upload any example building file as `building_geojson`
   - Enter the suggested height from the file properties
   - The `nyc_sensitive_sites.geojson` is loaded automatically as the default

2. **Shadow Tier 2 Module**:
   - Upload any example building file as `building_geojson`
   - Enter the suggested height from the file properties
   - Select jurisdiction (NYC, Boston, or generic)
   - Dates and times will auto-populate based on jurisdiction

3. **Transportation Tier 1 Module**:
   - Does not use GeoJSON files directly
   - Uses structured land use data (ITE codes, sizes, units)

## Coordinate System

All GeoJSON files use:
- **CRS**: WGS84 (EPSG:4326)
- **Coordinates**: [longitude, latitude] format
- **Location**: New York City area

## Adding Custom Data

You can add your own GeoJSON files to this folder. Make sure they:
- Use WGS84 coordinate system (EPSG:4326)
- Follow GeoJSON specification (RFC 7946)
- Include descriptive properties for better visualization
