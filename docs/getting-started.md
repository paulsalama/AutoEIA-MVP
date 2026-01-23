# Getting Started with AutoEIA

## Installation

### Prerequisites

- Node.js 18+ (for frontend)
- Python 3.9+ (for backend)
- Git

### Frontend Setup

```bash
cd platform/frontend
npm install
npm run dev
```

The frontend will be available at `http://localhost:3000`

### Backend Setup

```bash
cd platform/backend
pip install -r requirements.txt
python app.py
```

The backend API will be available at `http://localhost:8000`

## Quick Start

### Creating Your First Workflow

1. **Open the Platform**: Navigate to `http://localhost:3000` in your browser

2. **Browse Modules**: The left sidebar shows available analysis modules
   - Use the search box to filter modules
   - Select a category to narrow results

3. **Add a Module**: Drag a module from the sidebar onto the canvas
   - Example: Drag "Shadow Tier 1 Preliminary Screening"

4. **Configure Inputs**: Click on the module to configure its inputs
   - Upload a building GeoJSON file
   - Enter building height
   - Optionally upload sensitive sites data

5. **Add More Modules**: Drag additional modules and connect them
   - Example: Add "Shadow Tier 2 Detailed Analysis"
   - Connect Tier 1 output to Tier 2 input

6. **Run Workflow**: Click the "Run Workflow" button
   - Results will be displayed for each module
   - View maps, tables, and reports

7. **Save Workflow**: Click "Save Workflow" to download as JSON
   - Load saved workflows using "Load Workflow"

## Example Workflow: NYC Shadow Analysis

This example demonstrates a complete shadow analysis workflow for NYC.

### Step 1: Prepare Input Data

Create a building GeoJSON file (`building.geojson`):

```json
{
  "type": "FeatureCollection",
  "features": [{
    "type": "Feature",
    "geometry": {
      "type": "Polygon",
      "coordinates": [[
        [-73.9851, 40.7589],
        [-73.9841, 40.7589],
        [-73.9841, 40.7579],
        [-73.9851, 40.7579],
        [-73.9851, 40.7589]
      ]]
    },
    "properties": {
      "name": "Proposed Building"
    }
  }]
}
```

### Step 2: Create Workflow

1. Add "Shadow Tier 1 Preliminary Screening" module
2. Configure:
   - Upload `building.geojson`
   - Building height: 200 feet
   - Leave sensitive sites empty (will use default NYC dataset)

3. Add "Shadow Tier 2 Detailed Analysis" module
4. Connect Tier 1 → Tier 2
5. Configure Tier 2:
   - Analysis dates: `["2024-06-21", "2024-12-21"]` (solstices)
   - Jurisdiction: NYC

### Step 3: Run and Review

1. Click "Run Workflow"
2. Review Tier 1 results:
   - See which sensitive sites are potentially affected
   - Check if Tier 2 is triggered

3. Review Tier 2 results:
   - Interactive map showing shadow paths
   - Detailed report with shadow areas and times
   - Download visualizations for documentation

## Next Steps

- [Module Development Guide](./module-development.md) - Learn to create custom modules
- [API Documentation](./api-documentation.md) - Backend API reference
- [User Guide](./user-guide.md) - Comprehensive platform guide
