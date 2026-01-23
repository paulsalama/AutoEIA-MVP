# Module Development Guide

## Overview

This guide explains how to create custom analysis modules for the AutoEIA platform.

## Module Structure

Each module consists of:

```
modules/
└── your-module-name/
    ├── metadata.json          # Module metadata and schema
    ├── your_module_name.py    # Python implementation
    └── README.md              # Optional documentation
```

## Metadata Schema

The `metadata.json` file defines your module's interface:

```json
{
  "name": "your_module_name",
  "display_name": "Your Module Display Name",
  "description": "Detailed description of what your module does",
  "category": "category_name",
  "jurisdiction": ["generic", "NYC", "Boston"],
  "inputs": {
    "input_name": {
      "type": "geojson|number|string|array|object",
      "description": "Description of this input",
      "optional": false
    }
  },
  "outputs": {
    "output_name": {
      "type": "geojson|number|string|array|object|image|html",
      "description": "Description of this output"
    }
  }
}
```

### Required Fields

- **name**: Unique identifier (snake_case)
- **display_name**: Human-readable name
- **description**: Detailed description
- **category**: Analysis category (shadows, traffic, noise, etc.)
- **jurisdiction**: Array of supported jurisdictions
- **inputs**: Dictionary of input parameters
- **outputs**: Dictionary of output values

### Input/Output Types

Supported types:
- `geojson` - GeoJSON data
- `number` - Numeric value
- `string` - Text value
- `array` - List of values
- `object` - Dictionary/object
- `boolean` - True/False
- `image` - Image file path or base64
- `html` - HTML content (for visualizations)
- `text` - Plain text (for reports)

## Python Implementation

Your module's Python file must have an `execute()` function:

```python
def execute(inputs):
    """
    Execute module analysis

    Args:
        inputs (dict): Dictionary containing all input parameters

    Returns:
        dict: Dictionary containing all output values
    """
    # 1. Parse and validate inputs
    param1 = inputs.get('param1')
    if not param1:
        raise ValueError("param1 is required")

    # 2. Perform analysis
    result = perform_analysis(param1)

    # 3. Generate outputs
    outputs = {
        'output1': result,
        'summary_report': generate_report(result)
    }

    return outputs
```

### Best Practices

1. **Validate Inputs**: Always validate required inputs
2. **Handle Errors**: Use try/except and raise meaningful errors
3. **Document Code**: Include docstrings
4. **Use Type Hints**: Help users understand expected types
5. **Return All Outputs**: Return all outputs defined in metadata
6. **Test Standalone**: Module should be testable independently

## Example: Simple Buffer Module

### metadata.json

```json
{
  "name": "simple_buffer",
  "display_name": "Simple Buffer Analysis",
  "description": "Creates a buffer around a geometry",
  "category": "spatial",
  "jurisdiction": ["generic"],
  "inputs": {
    "geometry_geojson": {
      "type": "geojson",
      "description": "Input geometry",
      "optional": false
    },
    "buffer_distance_m": {
      "type": "number",
      "description": "Buffer distance in meters",
      "optional": false
    }
  },
  "outputs": {
    "buffer_geojson": {
      "type": "geojson",
      "description": "Buffered geometry"
    },
    "area_sqm": {
      "type": "number",
      "description": "Buffer area in square meters"
    }
  }
}
```

### simple_buffer.py

```python
import json
import geopandas as gpd
from shapely.geometry import shape

def execute(inputs):
    # Parse inputs
    geometry_geojson = inputs.get('geometry_geojson')
    buffer_distance = inputs.get('buffer_distance_m')

    # Validate
    if not geometry_geojson or not buffer_distance:
        raise ValueError("All inputs are required")

    # Convert to GeoDataFrame
    if isinstance(geometry_geojson, str):
        geometry_geojson = json.loads(geometry_geojson)

    gdf = gpd.GeoDataFrame.from_features(geometry_geojson['features'])
    if gdf.crs is None:
        gdf.set_crs(epsg=4326, inplace=True)

    # Project to metric CRS for accurate buffering
    gdf_projected = gdf.to_crs(epsg=3857)

    # Create buffer
    buffered = gdf_projected.buffer(buffer_distance)

    # Convert back to WGS84
    buffer_gdf = gpd.GeoDataFrame(geometry=buffered, crs='EPSG:3857')
    buffer_gdf = buffer_gdf.to_crs(epsg=4326)

    # Calculate area
    area_sqm = gdf_projected.buffer(buffer_distance).area.sum()

    # Return outputs
    return {
        'buffer_geojson': json.loads(buffer_gdf.to_json()),
        'area_sqm': float(area_sqm)
    }
```

## Working with GeoJSON

### Reading GeoJSON

```python
import geopandas as gpd
import json

# From input
geometry_geojson = inputs.get('geometry_geojson')
if isinstance(geometry_geojson, str):
    geometry_geojson = json.loads(geometry_geojson)

gdf = gpd.GeoDataFrame.from_features(geometry_geojson['features'])
if gdf.crs is None:
    gdf.set_crs(epsg=4326, inplace=True)
```

### Writing GeoJSON

```python
# Convert GeoDataFrame to GeoJSON
output_geojson = json.loads(gdf.to_json())

return {
    'output_geometry': output_geojson
}
```

## Creating Visualizations

### Map Visualization with Folium

```python
import folium

def create_map_visualization(gdf, center_lat, center_lon):
    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=15
    )

    folium.GeoJson(
        gdf,
        name='Layer Name',
        style_function=lambda x: {
            'fillColor': '#3388ff',
            'color': '#3388ff',
            'weight': 2,
            'fillOpacity': 0.6
        }
    ).add_to(m)

    folium.LayerControl().add_to(m)

    return m._repr_html_()

# In execute():
visualization_html = create_map_visualization(gdf, lat, lon)
return {
    'visualization': visualization_html
}
```

## Testing Your Module

Create a test script in your module directory:

```python
# test_module.py
from your_module_name import execute

def test_basic():
    inputs = {
        'param1': 'test_value',
        'param2': 123
    }

    result = execute(inputs)

    assert 'output1' in result
    assert result['output1'] is not None
    print("Test passed!")

if __name__ == '__main__':
    test_basic()
```

Run tests:

```bash
cd modules/your-module-name
python test_module.py
```

## Module Categories

Common categories:
- `shadows` - Shadow analysis
- `traffic` - Traffic and transportation
- `noise` - Noise impact
- `air_quality` - Air quality analysis
- `water` - Water resources
- `spatial` - General spatial analysis
- `environmental` - General environmental analysis

## Jurisdictions

Specify which jurisdictions your module supports:
- `generic` - Works anywhere
- `NYC` - New York City specific
- `Boston` - Boston specific
- Custom jurisdictions as needed

## Advanced Features

### Conditional Outputs

```python
def execute(inputs):
    threshold = inputs.get('threshold', 100)
    value = calculate_value()

    outputs = {
        'value': value,
        'threshold_exceeded': value > threshold
    }

    # Conditional output
    if value > threshold:
        outputs['detailed_analysis'] = perform_detailed_analysis()

    return outputs
```

### Progress Reporting (Future)

```python
def execute(inputs, progress_callback=None):
    total_steps = 5

    for i in range(total_steps):
        # Do work
        perform_step(i)

        # Report progress
        if progress_callback:
            progress_callback(i + 1, total_steps)

    return outputs
```

## Publishing Your Module

1. Create module directory with metadata.json and Python file
2. Test thoroughly
3. Document usage in README.md
4. Submit pull request to main repository
5. Module will be reviewed and added to the platform

## Resources

- [GeoJSON Specification](https://geojson.org/)
- [GeoPandas Documentation](https://geopandas.org/)
- [Folium Documentation](https://python-visualization.github.io/folium/)
- [Shapely Documentation](https://shapely.readthedocs.io/)
