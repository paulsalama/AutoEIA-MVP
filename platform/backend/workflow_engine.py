"""
Workflow Engine - Executes workflows with module chaining and conditionals
"""
from typing import Dict, List, Any
from module_loader import ModuleLoader


class WorkflowEngine:
    """Executes workflows by chaining modules together"""

    def __init__(self, module_loader: ModuleLoader):
        self.module_loader = module_loader

    def execute(self, workflow: Dict) -> Dict:
        """Execute a complete workflow"""
        nodes = workflow.get('nodes', [])
        edges = workflow.get('edges', [])

        # Build execution graph
        execution_order = self._topological_sort(nodes, edges)

        # Execute nodes in order
        results = {}
        node_outputs = {}

        for node_id in execution_order:
            node = self._get_node_by_id(nodes, node_id)
            if not node:
                continue

            try:
                # Get module metadata
                module_data = node.get('data', {}).get('moduleData', {})
                module_name = module_data.get('name')

                if not module_name:
                    results[node_id] = {'error': 'No module name specified'}
                    continue

                # Gather inputs from connected nodes
                inputs = self._gather_inputs(node_id, edges, node_outputs)

                # Add any configured inputs from the node
                if 'configuredInputs' in node.get('data', {}):
                    inputs.update(node['data']['configuredInputs'])

                # Execute module
                output = self.module_loader.execute_module(module_name, inputs)

                # Store outputs for downstream nodes
                node_outputs[node_id] = output
                results[node_id] = {
                    'success': True,
                    'module': module_name,
                    'output': output
                }

            except Exception as e:
                results[node_id] = {
                    'success': False,
                    'error': str(e)
                }

        return results

    def _topological_sort(self, nodes: List[Dict], edges: List[Dict]) -> List[str]:
        """Sort nodes in execution order using topological sort"""
        # Build adjacency list
        graph = {node['id']: [] for node in nodes}
        in_degree = {node['id']: 0 for node in nodes}

        for edge in edges:
            source = edge['source']
            target = edge['target']
            if source in graph and target in graph:
                graph[source].append(target)
                in_degree[target] += 1

        # Find nodes with no incoming edges
        queue = [node_id for node_id, degree in in_degree.items() if degree == 0]
        result = []

        while queue:
            node_id = queue.pop(0)
            result.append(node_id)

            # Reduce in-degree for neighbors
            for neighbor in graph[node_id]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        # Check for cycles
        if len(result) != len(nodes):
            raise ValueError("Workflow contains cycles")

        return result

    def _get_node_by_id(self, nodes: List[Dict], node_id: str) -> Dict:
        """Get a node by its ID"""
        for node in nodes:
            if node['id'] == node_id:
                return node
        return None

    def _gather_inputs(self, node_id: str, edges: List[Dict], node_outputs: Dict) -> Dict:
        """Gather inputs for a node from connected upstream nodes"""
        inputs = {}

        # Find all edges that target this node
        for edge in edges:
            if edge['target'] == node_id:
                source_id = edge['source']
                if source_id in node_outputs:
                    # Merge outputs from source node
                    source_output = node_outputs[source_id]
                    if isinstance(source_output, dict):
                        inputs.update(source_output)

        return inputs

    def validate_workflow(self, workflow: Dict) -> Dict:
        """Validate a workflow before execution"""
        errors = []
        warnings = []

        nodes = workflow.get('nodes', [])
        edges = workflow.get('edges', [])

        # Check for empty workflow
        if not nodes:
            errors.append("Workflow has no nodes")

        # Check for cycles
        try:
            self._topological_sort(nodes, edges)
        except ValueError as e:
            errors.append(str(e))

        # Validate each node
        for node in nodes:
            module_data = node.get('data', {}).get('moduleData', {})
            module_name = module_data.get('name')

            if not module_name:
                errors.append(f"Node {node['id']} has no module assigned")
                continue

            # Check if module exists
            module_metadata = self.module_loader.get_module(module_name)
            if not module_metadata:
                errors.append(f"Module {module_name} not found")
                continue

            # Check required inputs
            required_inputs = {
                k: v for k, v in module_metadata.get('inputs', {}).items()
                if not v.get('optional', False)
            }

            # TODO: Validate that required inputs will be satisfied

        return {
            'valid': len(errors) == 0,
            'errors': errors,
            'warnings': warnings
        }
