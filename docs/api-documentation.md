# API Documentation

## Overview

The AutoEIA backend provides a REST API for module management and workflow execution.

Base URL: `http://localhost:8000`

## Endpoints

### Health Check

Check if the API is running.

```
GET /api/health
```

**Response:**
```json
{
  "status": "healthy",
  "message": "AutoEIA backend is running"
}
```

---

### Get All Modules

Retrieve a list of all available modules.

```
GET /api/modules
```

**Response:**
```json
{
  "modules": [
    {
      "name": "shadow_tier1_screening",
      "display_name": "Shadow Tier 1 Preliminary Screening",
      "description": "Initial geospatial proximity analysis...",
      "category": "shadows",
      "jurisdiction": ["NYC", "generic"],
      "inputs": { ... },
      "outputs": { ... },
      "path": "/path/to/module",
      "python_file": "/path/to/module/file.py"
    }
  ]
}
```

---

### Get Module Details

Retrieve metadata for a specific module.

```
GET /api/modules/{module_name}
```

**Parameters:**
- `module_name` (path): The unique name of the module

**Response:**
```json
{
  "name": "shadow_tier1_screening",
  "display_name": "Shadow Tier 1 Preliminary Screening",
  "description": "...",
  "category": "shadows",
  "jurisdiction": ["NYC", "generic"],
  "inputs": {
    "building_geojson": {
      "type": "geojson",
      "description": "Building footprint geometry",
      "optional": false
    }
  },
  "outputs": {
    "triggered": {
      "type": "boolean",
      "description": "Whether detailed analysis is triggered"
    }
  }
}
```

**Error Response (404):**
```json
{
  "error": "Module not found"
}
```

---

### Execute Workflow

Execute a complete workflow with multiple modules.

```
POST /api/workflow/execute
```

**Request Body:**
```json
{
  "name": "Shadow Analysis Workflow",
  "nodes": [
    {
      "id": "node-1",
      "type": "default",
      "position": { "x": 100, "y": 100 },
      "data": {
        "label": "Shadow Tier 1",
        "moduleData": {
          "name": "shadow_tier1_screening"
        },
        "configuredInputs": {
          "building_geojson": { ... },
          "building_height_ft": 200
        }
      }
    },
    {
      "id": "node-2",
      "type": "default",
      "position": { "x": 400, "y": 100 },
      "data": {
        "label": "Shadow Tier 2",
        "moduleData": {
          "name": "shadow_tier2_detailed"
        },
        "configuredInputs": {
          "analysis_dates": ["2024-06-21"]
        }
      }
    }
  ],
  "edges": [
    {
      "id": "edge-1",
      "source": "node-1",
      "target": "node-2",
      "type": "smoothstep"
    }
  ]
}
```

**Response (Success):**
```json
{
  "success": true,
  "results": {
    "node-1": {
      "success": true,
      "module": "shadow_tier1_screening",
      "output": {
        "triggered": true,
        "affected_sites_count": 3,
        "summary_report": "...",
        "visualization": "<html>..."
      }
    },
    "node-2": {
      "success": true,
      "module": "shadow_tier2_detailed",
      "output": {
        "shadow_geometries": { ... },
        "affected_area_sqft": 15000,
        "summary_report": "..."
      }
    }
  }
}
```

**Response (Error):**
```json
{
  "success": false,
  "error": "Error message describing what went wrong"
}
```

**Error Codes:**
- `400` - Invalid workflow structure
- `500` - Server error during execution

---

### Get Datasets

Retrieve a list of available reference datasets.

```
GET /api/datasets
```

**Response:**
```json
{
  "datasets": [
    {
      "name": "nyc_sensitive_sites.geojson",
      "path": "/path/to/datasets/nyc_sensitive_sites.geojson",
      "size": 12345
    }
  ]
}
```

---

### Download Dataset

Download a specific dataset file.

```
GET /api/datasets/{dataset_name}
```

**Parameters:**
- `dataset_name` (path): The name of the dataset file

**Response:**
- File download (Content-Type depends on file type)

**Error Response (404):**
```json
{
  "error": "Dataset not found"
}
```

---

## Workflow Execution Flow

1. **Client sends workflow**: POST to `/api/workflow/execute` with nodes and edges
2. **Server validates**: Checks workflow structure and module existence
3. **Topological sort**: Determines execution order based on dependencies
4. **Execute modules**: Runs each module in order, passing outputs to downstream modules
5. **Return results**: Sends back results for each node

## Module Input/Output Chaining

Modules are automatically chained based on the workflow graph:

```
Node A (outputs: {result: 123})
   ↓
Node B (receives: {result: 123} as inputs)
```

The workflow engine:
1. Identifies upstream nodes
2. Collects their outputs
3. Merges them into the downstream node's inputs
4. Adds any configured inputs from the node itself

## Error Handling

### Module Execution Errors

If a module fails during execution:

```json
{
  "success": true,
  "results": {
    "node-1": {
      "success": true,
      "module": "module_a",
      "output": { ... }
    },
    "node-2": {
      "success": false,
      "error": "ValueError: required input 'param' is missing"
    }
  }
}
```

The workflow continues executing other independent nodes, but dependent nodes may fail.

### Validation Errors

Invalid workflow structures return 400:

```json
{
  "success": false,
  "error": "Invalid workflow structure"
}
```

## Data Formats

### GeoJSON

All geospatial data uses GeoJSON format (EPSG:4326 - WGS84):

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "geometry": {
        "type": "Polygon",
        "coordinates": [[[-73.98, 40.75], ...]]
      },
      "properties": {
        "name": "Building A"
      }
    }
  ]
}
```

### Visualizations

Map visualizations are returned as HTML strings that can be rendered in an iframe:

```json
{
  "visualization": "<div>...</div>"
}
```

### Reports

Text reports use plain text with formatting:

```json
{
  "summary_report": "Shadow Analysis Results\n========================\n\n..."
}
```

## Rate Limiting

Currently no rate limiting is implemented. This may be added in future versions.

## Authentication

Currently no authentication is required. This may be added in future versions for:
- User-specific workflows
- Private modules
- Usage tracking

## CORS

CORS is enabled for all origins to support local development. Production deployments should restrict this.

## WebSocket Support (Future)

Future versions may add WebSocket support for:
- Real-time progress updates during workflow execution
- Live visualization updates
- Collaborative editing

## Example Usage

### JavaScript/Fetch

```javascript
// Get all modules
const modules = await fetch('http://localhost:8000/api/modules')
  .then(r => r.json());

// Execute workflow
const workflow = {
  nodes: [...],
  edges: [...]
};

const results = await fetch('http://localhost:8000/api/workflow/execute', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(workflow)
}).then(r => r.json());
```

### Python

```python
import requests

# Get all modules
response = requests.get('http://localhost:8000/api/modules')
modules = response.json()

# Execute workflow
workflow = {
    'nodes': [...],
    'edges': [...]
}

response = requests.post(
    'http://localhost:8000/api/workflow/execute',
    json=workflow
)
results = response.json()
```

### cURL

```bash
# Health check
curl http://localhost:8000/api/health

# Get modules
curl http://localhost:8000/api/modules

# Execute workflow
curl -X POST http://localhost:8000/api/workflow/execute \
  -H "Content-Type: application/json" \
  -d @workflow.json
```
