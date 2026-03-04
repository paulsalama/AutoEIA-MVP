# AutoEIA Module Author Guide

AutoEIA analysis modules are self-contained units that accept geospatial and configuration inputs, run a regulatory analysis, and return structured outputs. This guide covers everything needed to write, test, and share a module.

---

## 1. What is a Module?

A module is a directory inside `modules/` containing two required files:

```
modules/my_module/
├── metadata.json       ← declares inputs, outputs, and metadata
└── my_module.py        ← implements execute(inputs) -> dict
```

Optionally:
```
└── test_fixture.json   ← sample inputs for autoeia test
```

The platform discovers modules by scanning `modules/` at startup. Any subdirectory with a valid `metadata.json` and matching Python file is loaded automatically.

---

## 2. Quick Start

```bash
python autoeia.py new my_module --category shadows
python autoeia.py test modules/my_module
```

---

## 3. `metadata.json` Reference

| Field | Required | Type | Description |
|---|---|---|---|
| `name` | ✓ | string | Unique identifier in `snake_case`. Must match the Python filename. |
| `display_name` | ✓ | string | Human-readable name shown in the UI. |
| `description` | ✓ | string | What the module analyzes and which regulatory framework it implements. |
| `category` | ✓ | string | Groups module in the UI palette. See valid values below. |
| `jurisdiction` | ✓ | array | Where this methodology applies, e.g. `["NYC"]` or `["NYC", "generic"]`. |
| `emoji` | — | string | Single emoji for visual identification, e.g. `"☀️"`. |
| `inputs` | ✓ | object | Input port definitions (see Input Types). |
| `outputs` | ✓ | object | Output port definitions (see Output Types). |

**Valid `category` values:**
`shadows` · `transportation` · `environmental_justice` · `air_quality` · `noise` · `hazardous_materials` · `socioeconomic` · `infrastructure` · `natural_resources` · `other`

**Naming rules:**
- `name` must be snake_case: `^[a-z][a-z0-9_]*$`
- The Python file must be named `{name}.py` (e.g. `name: "wind_analysis"` → `wind_analysis.py`)
- Directory name can differ (convention: use hyphens, e.g. `modules/wind-analysis/`)

---

## 4. Input Types

Each entry in `inputs` has at minimum `type` and `description`. Use `"optional": true` for non-required inputs.

| Type | UI Widget | Notes |
|---|---|---|
| `geojson` | File picker (.geojson, .json) | Value arrives as a parsed dict (FeatureCollection) |
| `number` | Number input | Value arrives as a Python float |
| `string` | Text input (single line) | Value arrives as a str |
| `text` | Textarea (multi-line) | Value arrives as a str |
| `boolean` | Toggle switch | Value arrives as True/False |
| `array` | JSON textarea | Value arrives as a Python list |
| `object` | JSON textarea | Value arrives as a Python dict |
| `enum` | Dropdown | Requires `"enum": ["option1", "option2", ...]`. Value arrives as a str. |
| `multiselect` | Checkbox group | Requires `"options": ["opt1", "opt2", ...]`. Value arrives as a list of str. |
| `obj` | File picker (.obj) | Value arrives as a raw string (OBJ file text) |

**Example input with all fields:**
```json
"building_height_ft": {
  "type": "number",
  "description": "Building height in feet including all rooftop equipment.",
  "optional": false,
  "default": 100
}
```

---

## 5. Output Types

Each entry in `outputs` has `type` and `description`. The results panel renders each output based on its type.

| Type | How it's displayed | Notes |
|---|---|---|
| `html` | Rendered in an iframe | Return a Folium map via `m._repr_html_()` or any HTML string |
| `geojson` | Interactive mini-map | Return a GeoJSON FeatureCollection dict |
| `text` | Formatted text panel | Plain text or Markdown |
| `object` | Key-value tree | Return any JSON-serialisable dict |
| `number` | Numeric badge | Return a Python int or float |
| `string` | Text badge | Return a str |
| `array` | List view | Return a Python list |
| `boolean` | Yes/No badge | Return True or False |

---

## 6. The `execute()` Contract

```python
def execute(inputs: dict) -> dict:
    ...
```

**What's in `inputs`:**
- All values the user configured in the node panel (keys match `metadata.json inputs`)
- All outputs from every upstream node in the workflow (merged automatically)
- So a module downstream of shadow analysis can read `inputs.get("shadow_polygons")`

**What `execute()` must return:**
- A `dict` whose keys include **every key declared in `metadata.json outputs`**
- Missing keys cause the platform to report an error
- Extra keys are ignored (useful for passing data to downstream modules)
- Must be JSON-serialisable (no numpy arrays, no geopandas DataFrames — convert first)

**Error handling:**
```python
# Raise ValueError for bad inputs — the platform catches this and shows a clean error
if not building_geojson:
    raise ValueError("building_geojson is required")

# Raise RuntimeError for analysis failures
if no_data_available:
    raise RuntimeError("No census tract data found for this location")
```

**Minimal example:**
```python
def execute(inputs: dict) -> dict:
    import json, geopandas as gpd
    from shapely.ops import unary_union

    building_geojson = inputs.get("building_geojson")
    if not building_geojson:
        raise ValueError("building_geojson is required")
    if isinstance(building_geojson, str):
        building_geojson = json.loads(building_geojson)

    gdf = gpd.GeoDataFrame.from_features(building_geojson["features"])
    centroid = unary_union(gdf.geometry).centroid

    return {
        "latitude": centroid.y,
        "longitude": centroid.x,
        "summary_report": f"Project centroid: {centroid.y:.5f}°N, {centroid.x:.5f}°W",
    }
```

---

## 7. Testing Your Module

**Structure check only (no execution):**
```bash
python autoeia.py validate modules/my_module
```

**Full test (validate + run + check outputs):**
```bash
python autoeia.py test modules/my_module
```

The test command looks for `test_fixture.json` in the module directory. Create one:

```json
{
  "building_geojson": {
    "type": "FeatureCollection",
    "features": [{
      "type": "Feature",
      "properties": {},
      "geometry": {
        "type": "Polygon",
        "coordinates": [[
          [-73.9863, 40.7484], [-73.9848, 40.7484],
          [-73.9848, 40.7494], [-73.9863, 40.7494],
          [-73.9863, 40.7484]
        ]]
      }
    }]
  }
}
```

Use `--fixture` to point at an existing file:
```bash
python autoeia.py test modules/my_module --fixture datasets/example_building_midtown.geojson
```

**What the test checks:**
1. `metadata.json` passes schema validation
2. `{name}.py` (or `main.py`) exists and imports without errors
3. `execute()` function is present
4. `execute(fixture)` runs without raising an exception
5. Every key declared in `metadata.json outputs` is present in the returned dict

---

## 8. Reference Datasets

Some modules depend on external regulatory or spatial datasets that must be downloaded once and cached locally before the module can run. Examples include:

- DAC module: NYS Disadvantaged Communities census tracts (data.ny.gov)
- Future: EPA ECHO facility database, Census ACS data, DOT traffic counts, NWI wetlands

**Convention**: Include a `fetch_data.py` in the module directory exposing a `fetch()` function with no required arguments.

```
modules/my_module/
├── metadata.json
├── my_module.py
├── fetch_data.py      ← optional: download reference datasets
└── test_fixture.json
```

**`fetch_data.py` template:**
```python
from pathlib import Path

CACHE = Path(__file__).parent.parent.parent / "datasets" / "my_data.geojson"


def fetch():
    """Download and cache all reference datasets this module needs."""
    import urllib.request
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    print("Downloading my_data.geojson...")
    urllib.request.urlretrieve("https://example.gov/api/data.geojson", CACHE)
    print(f"Saved to {CACHE}")
```

Run it via the SDK CLI:
```bash
python autoeia.py fetch modules/my_module
```

**In `execute()`**, raise a clear `RuntimeError` if the cache is missing so the user knows exactly what to do:
```python
if not CACHE.exists():
    raise RuntimeError(
        "Reference dataset not found. Run:  python autoeia.py fetch modules/my_module"
    )
```

The platform does not call `fetch_data.py` automatically — it is a one-time setup step.

---

## 9. Complete Working Example

A minimal module that finds the centroid of the project footprint and generates a map:

**`modules/centroid_mapper/metadata.json`:**
```json
{
  "name": "centroid_mapper",
  "display_name": "Project Centroid Mapper",
  "emoji": "📍",
  "description": "Calculates the geographic centroid of the project footprint and generates an interactive map.",
  "category": "other",
  "jurisdiction": ["NYC", "generic"],
  "inputs": {
    "building_geojson": {
      "type": "geojson",
      "description": "Project site boundary (GeoJSON FeatureCollection).",
      "optional": false
    }
  },
  "outputs": {
    "visualization": {
      "type": "html",
      "description": "Folium map showing the project centroid."
    },
    "summary_report": {
      "type": "text",
      "description": "Centroid coordinates in decimal degrees."
    }
  }
}
```

**`modules/centroid_mapper/centroid_mapper.py`:**
```python
import json
import folium
import geopandas as gpd
from shapely.ops import unary_union


def execute(inputs: dict) -> dict:
    building_geojson = inputs.get("building_geojson")
    if not building_geojson:
        raise ValueError("building_geojson is required")
    if isinstance(building_geojson, str):
        building_geojson = json.loads(building_geojson)

    gdf = gpd.GeoDataFrame.from_features(building_geojson["features"])
    if gdf.crs is None:
        gdf.set_crs(epsg=4326, inplace=True)
    centroid = unary_union(gdf.geometry).centroid
    lat, lon = centroid.y, centroid.x

    m = folium.Map(location=[lat, lon], zoom_start=15, tiles="CartoDB positron")
    folium.Marker([lat, lon], tooltip="Project Centroid").add_to(m)

    return {
        "visualization": m._repr_html_(),
        "summary_report": f"Project centroid: {lat:.6f}°N, {lon:.6f}°W",
    }
```

---

## 10. Reference Module

For a full production example — solar position, UTM projection, site intersection analysis, Folium visualization, and a structured Markdown report — see:

**`modules/shadow-tier-3/shadow_tier3_projection.py`**

This module implements CEQR Technical Manual Chapter 8 Tier 3 shadow analysis and demonstrates the full pattern: input parsing → spatial analysis → report generation → visualization.

---

## 11. Publishing a Module

To share a module:
1. Run `python autoeia.py test modules/my_module` — all checks must pass
2. Zip the module directory: `my_module.zip` containing `metadata.json`, `my_module.py`, `test_fixture.json`
3. Share the zip or host the directory in a public GitHub repository

The recipient drops the directory into their `modules/` folder and restarts the backend — the module appears automatically in the UI.
