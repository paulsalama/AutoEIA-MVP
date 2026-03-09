# AutoEIA

Visual workflow platform for Environmental Impact Analysis. Engineers drag analysis modules onto a canvas, connect them, configure inputs, and run multi-step EIA calculations — no code required.

Built around the NYC CEQR Technical Manual methodology, with a module SDK so anyone can add new analysis types.

---

## Quick Start

**Backend** (Python, port 8000)
```bash
cd platform/backend
pip install -r requirements.txt
python app.py
```

**Frontend** (React, port 3000)
```bash
cd platform/frontend
npm install
npm run dev
```

Open http://localhost:3000. Load an example workflow from `workflows/` to get started immediately.

---

## Available Modules

| Module | Category | Description |
|--------|----------|-------------|
| 🔍 Shadow Tier 1 | shadows | CEQR proximity screening — 4.3× height buffer vs. sensitive sites |
| 🧭 Shadow Tier 2 | shadows | CEQR directional screen — ±108° no-shadow zone elimination |
| ☀️ Shadow Tier 3 | shadows | 3D shadow projection using pysolar + UTM geometry |
| 🏗️ Shadow Tier 3 (OBJ) | shadows | Tier 3 variant accepting a 3D OBJ building model |
| 🚗 Transportation Tier 1 | transportation | Trip generation screening |
| 🏛️ DAC Assessment | equity | Disadvantaged Community analysis (NYS Climate Act) |

---

## Example Workflows

The `workflows/` directory contains ready-to-run examples:

- **Shadows_Tier_1-3.json** — Full CEQR shadow analysis chain (Tier 1 → 2 → 3)

Load via the **Load Workflow** button in the canvas toolbar.

---

## Module SDK

Modules are self-contained Python files with a `metadata.json` descriptor. Any developer can write one.

**→ [sdk/MODULE_GUIDE.md](sdk/MODULE_GUIDE.md)** — complete author guide with worked example

**CLI:**
```bash
python autoeia.py list                        # list installed modules
python autoeia.py new my_module               # scaffold a new module
python autoeia.py validate modules/my_module  # schema-check metadata.json
python autoeia.py test modules/my_module      # run with test fixture
python autoeia.py fetch modules/dac           # download required datasets
```

---

## Project Structure

```
AutoEIA/
├── autoeia.py              # Module developer CLI
├── modules/                # Analysis modules (each has metadata.json + .py)
│   ├── shadow-tier-1/
│   ├── shadow-tier-2/
│   ├── shadow-tier-3/
│   ├── shadow-tier-3-obj/
│   ├── transportation-tier-1/
│   └── dac/
├── datasets/               # Reference datasets (GeoJSON)
├── workflows/              # Example/saved workflow JSON files
├── sdk/
│   ├── MODULE_GUIDE.md     # Module authoring guide
│   └── metadata_schema.json
├── platform/
│   ├── frontend/           # React + ReactFlow
│   └── backend/            # Flask execution engine
└── docs/                   # Additional documentation
```

---

## Tech Stack

- **Frontend**: React, ReactFlow, Folium (map output)
- **Backend**: Flask, GeoPandas, Shapely, pysolar
- **Analysis**: CEQR Chapter 8 shadow methodology (NYC)

---

## License

TBD
