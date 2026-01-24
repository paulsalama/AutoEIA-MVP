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

### Quick Start (Recommended)

Start both frontend and backend with a single command:

```bash
./dev.sh
```

This script will:
- Create and activate Python virtual environment (using uv)
- Install all Python dependencies
- Install all Node.js dependencies
- Start the backend on `http://localhost:8000`
- Start the frontend on `http://localhost:5173`
- Gracefully shutdown both services with `Ctrl+C`

### Manual Setup

If you prefer to run services separately:

#### Frontend
```bash
cd platform/frontend
npm install
npm run dev
```

#### Backend
```bash
cd platform/backend
uv venv                          # Create virtual environment
uv pip install -r requirements.txt  # Install dependencies
uv run python app.py             # Run the application
```

### VS Code Debugging

This project includes VS Code launch configurations for debugging:

1. **Backend: Flask** - Debug the Python Flask backend
2. **Frontend: Vite Dev Server** - Run the Vite dev server
3. **Frontend: Chrome Debug** - Debug React app in Chrome
4. **Full Stack: Frontend + Backend** - Debug both simultaneously
5. **Full Stack: With Browser** - Debug backend, frontend, and browser together

To use:
1. Open the project in VS Code
2. Go to Run and Debug (Cmd+Shift+D / Ctrl+Shift+D)
3. Select a configuration from the dropdown
4. Press F5 or click the green play button

The compound configurations will start multiple services and allow you to debug across the entire stack.

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
