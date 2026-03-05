"""
AutoEIA Backend - Flask API for workflow execution
"""
from flask import Flask, request, jsonify, send_file, Response, stream_with_context
from flask_cors import CORS
import json
import os
from pathlib import Path
from module_loader import ModuleLoader
from workflow_engine import WorkflowEngine

app = Flask(__name__)
CORS(app)

# Initialize module loader and workflow engine
module_loader = ModuleLoader()
workflow_engine = WorkflowEngine(module_loader)

# Paths
MODULES_DIR = Path(__file__).parent.parent.parent / 'modules'
DATASETS_DIR = Path(__file__).parent.parent.parent / 'datasets'


@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({'status': 'healthy', 'message': 'AutoEIA backend is running'})


@app.route('/api/modules', methods=['GET'])
def get_modules():
    """Get list of all available modules"""
    try:
        modules = module_loader.load_all_modules(MODULES_DIR)
        return jsonify({'modules': modules})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/modules/<module_name>', methods=['GET'])
def get_module(module_name):
    """Get metadata for a specific module"""
    try:
        module = module_loader.get_module(module_name)
        if module:
            return jsonify(module)
        else:
            return jsonify({'error': 'Module not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/workflow/execute', methods=['POST'])
def execute_workflow():
    """Execute a workflow"""
    try:
        workflow_data = request.json

        # Validate workflow structure
        if 'nodes' not in workflow_data or 'edges' not in workflow_data:
            return jsonify({'error': 'Invalid workflow structure'}), 400

        # Execute workflow
        results = workflow_engine.execute(workflow_data)

        return jsonify({
            'success': True,
            'results': results
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/workflow/stream', methods=['POST'])
def stream_workflow():
    """Execute a workflow and stream per-node results as Server-Sent Events."""
    workflow_data = request.json
    if not workflow_data or 'nodes' not in workflow_data or 'edges' not in workflow_data:
        return jsonify({'error': 'Invalid workflow structure'}), 400

    def generate():
        try:
            for node_id, result in workflow_engine.execute_streaming(workflow_data):
                msg = json.dumps({'node_id': node_id, 'result': result})
                yield 'data: ' + msg + chr(10) + chr(10)
        except Exception as e:
            yield 'data: ' + json.dumps({'error': str(e)}) + chr(10) + chr(10)
        yield 'data: {"done": true}' + chr(10) + chr(10)

    return Response(
        stream_with_context(generate()),
        content_type='text/event-stream',
        headers={'X-Accel-Buffering': 'no', 'Cache-Control': 'no-cache'},
    )


@app.route('/api/datasets', methods=['GET'])
def get_datasets():
    """Get list of available datasets"""
    try:
        datasets = []
        if DATASETS_DIR.exists():
            for file in DATASETS_DIR.iterdir():
                if file.is_file():
                    datasets.append({
                        'name': file.name,
                        'path': str(file),
                        'size': file.stat().st_size
                    })
        return jsonify({'datasets': datasets})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/datasets/<dataset_name>', methods=['GET'])
def get_dataset(dataset_name):
    """Download a specific dataset"""
    try:
        dataset_path = DATASETS_DIR / dataset_name
        if dataset_path.exists() and dataset_path.is_file():
            return send_file(dataset_path)
        else:
            return jsonify({'error': 'Dataset not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    # Load modules on startup
    module_loader.load_all_modules(MODULES_DIR)

    # Run the app
    app.run(
        host='0.0.0.0',
        port=8000,
        debug=True
    )
