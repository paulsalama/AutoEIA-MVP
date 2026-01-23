"""
Module Loader - Loads and validates analysis modules
"""
import json
import importlib.util
import sys
from pathlib import Path
from typing import Dict, List, Optional


class ModuleLoader:
    """Loads and manages analysis modules"""

    def __init__(self):
        self.modules = {}
        self.module_registry = {}

    def load_all_modules(self, modules_dir: Path) -> List[Dict]:
        """Load all modules from the modules directory"""
        self.modules = {}
        self.module_registry = {}

        if not modules_dir.exists():
            print(f"Warning: Modules directory not found: {modules_dir}")
            return []

        # Scan for module directories
        for module_path in modules_dir.iterdir():
            if module_path.is_dir():
                try:
                    self.load_module(module_path)
                except Exception as e:
                    print(f"Error loading module {module_path.name}: {e}")

        return list(self.modules.values())

    def load_module(self, module_path: Path) -> Optional[Dict]:
        """Load a single module from its directory"""
        # Load metadata
        metadata_file = module_path / 'metadata.json'
        if not metadata_file.exists():
            print(f"Warning: No metadata.json found in {module_path}")
            return None

        with open(metadata_file, 'r') as f:
            metadata = json.load(f)

        # Validate metadata
        if not self.validate_metadata(metadata):
            print(f"Warning: Invalid metadata in {module_path}")
            return None

        # Find the main Python file (should match module name or be main.py)
        module_name = metadata['name']
        python_file = module_path / f"{module_name}.py"
        if not python_file.exists():
            python_file = module_path / "main.py"
        if not python_file.exists():
            print(f"Warning: No Python file found for module {module_name}")
            return None

        # Store module info
        metadata['path'] = str(module_path)
        metadata['python_file'] = str(python_file)
        self.modules[module_name] = metadata

        # Load the Python module for execution
        self._load_python_module(module_name, python_file)

        return metadata

    def _load_python_module(self, module_name: str, python_file: Path):
        """Load a Python module dynamically"""
        try:
            spec = importlib.util.spec_from_file_location(module_name, python_file)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
                self.module_registry[module_name] = module
        except Exception as e:
            print(f"Error loading Python module {module_name}: {e}")

    def validate_metadata(self, metadata: Dict) -> bool:
        """Validate module metadata against schema"""
        required_fields = [
            'name',
            'display_name',
            'description',
            'category',
            'jurisdiction',
            'inputs',
            'outputs'
        ]

        for field in required_fields:
            if field not in metadata:
                return False

        # Validate inputs and outputs structure
        if not isinstance(metadata['inputs'], dict):
            return False
        if not isinstance(metadata['outputs'], dict):
            return False

        return True

    def get_module(self, module_name: str) -> Optional[Dict]:
        """Get metadata for a specific module"""
        return self.modules.get(module_name)

    def get_python_module(self, module_name: str):
        """Get the loaded Python module for execution"""
        return self.module_registry.get(module_name)

    def execute_module(self, module_name: str, inputs: Dict) -> Dict:
        """Execute a module with given inputs"""
        if module_name not in self.module_registry:
            raise ValueError(f"Module {module_name} not loaded")

        python_module = self.module_registry[module_name]

        # Look for execute or run function
        if hasattr(python_module, 'execute'):
            return python_module.execute(inputs)
        elif hasattr(python_module, 'run'):
            return python_module.run(inputs)
        else:
            raise ValueError(f"Module {module_name} has no execute() or run() function")
