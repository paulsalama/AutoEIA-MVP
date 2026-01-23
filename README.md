# AutoEIA Module Orchestration Platform

A Visual Workflow Platform for Environmental Impact Analysis

## Overview

The AutoEIA Module Orchestration Platform enables environmental review practitioners to discover, configure, and chain together standardized analysis modules—such as shadow studies, traffic analysis, and proximity assessments—without writing code.

## Project Structure

```
autoeia/
├── modules/                 # Analysis modules (shadow, traffic, etc.)
├── datasets/               # Reference datasets (NYC sensitive sites, etc.)
├── tests/                  # Test suites
├── platform/
│   ├── frontend/          # React + ReactFlow UI
│   └── backend/           # Python execution engine
├── docs/                  # Documentation
└── README.md
```

## Features

- **Visual Workflow Builder**: Drag-and-drop interface for constructing analysis workflows
- **Module Repository**: Searchable registry of standardized analysis modules
- **Shadow Analysis**: Tier 1-3 shadow analysis modules
- **Module Chaining**: Connect modules with conditional branching
- **Multiple Output Types**: GeoJSON, CSV, images, and reports
- **Workflow Persistence**: Save and load workflow configurations

## Getting Started

### Frontend
```bash
cd platform/frontend
npm install
npm run dev
```

### Backend
```bash
cd platform/backend
pip install -r requirements.txt
python app.py
```

## Technology Stack

- **Frontend**: React, ReactFlow, Leaflet
- **Backend**: Python
- **Deployment**: Vercel (frontend), Render (backend)

## Documentation

See the [docs](./docs) directory for:
- Module development guide
- API documentation
- User tutorials

## License

TBD
