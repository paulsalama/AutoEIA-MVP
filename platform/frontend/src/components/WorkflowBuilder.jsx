import { useCallback, useState } from 'react'
import ReactFlow, {
  MiniMap,
  Controls,
  Background,
  useNodesState,
  useEdgesState,
  addEdge,
  MarkerType,
} from 'reactflow'
import 'reactflow/dist/style.css'
import './WorkflowBuilder.css'

const initialNodes = []
const initialEdges = []

function WorkflowBuilder({ selectedNode, onNodeSelect }) {
  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes)
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges)
  const [workflowName, setWorkflowName] = useState('Untitled Workflow')

  const onConnect = useCallback(
    (params) =>
      setEdges((eds) =>
        addEdge(
          {
            ...params,
            type: 'smoothstep',
            animated: true,
            markerEnd: {
              type: MarkerType.ArrowClosed,
            },
          },
          eds
        )
      ),
    [setEdges]
  )

  const onNodeClick = useCallback(
    (event, node) => {
      onNodeSelect(node)
    },
    [onNodeSelect]
  )

  const onDrop = useCallback(
    (event) => {
      event.preventDefault()

      const reactFlowBounds = event.target.getBoundingClientRect()
      const moduleData = JSON.parse(
        event.dataTransfer.getData('application/reactflow')
      )

      const position = {
        x: event.clientX - reactFlowBounds.left - 100,
        y: event.clientY - reactFlowBounds.top - 50,
      }

      const newNode = {
        id: `${moduleData.name}-${Date.now()}`,
        type: 'default',
        position,
        data: {
          label: moduleData.display_name,
          moduleData: moduleData,
        },
        style: {
          background: '#fff',
          border: '2px solid #667eea',
          borderRadius: '8px',
          padding: '10px',
          minWidth: '200px',
        },
      }

      setNodes((nds) => nds.concat(newNode))
    },
    [setNodes]
  )

  const onDragOver = useCallback((event) => {
    event.preventDefault()
    event.dataTransfer.dropEffect = 'move'
  }, [])

  const handleRunWorkflow = async () => {
    console.log('Running workflow with nodes:', nodes)
    console.log('Edges:', edges)

    // TODO: Implement API call to backend
    alert('Workflow execution will be implemented with backend integration')
  }

  const handleSaveWorkflow = () => {
    const workflow = {
      name: workflowName,
      nodes,
      edges,
      createdAt: new Date().toISOString(),
    }

    const blob = new Blob([JSON.stringify(workflow, null, 2)], {
      type: 'application/json',
    })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${workflowName.replace(/\s+/g, '_')}.json`
    link.click()
    URL.revokeObjectURL(url)
  }

  const handleLoadWorkflow = (event) => {
    const file = event.target.files[0]
    if (!file) return

    const reader = new FileReader()
    reader.onload = (e) => {
      try {
        const workflow = JSON.parse(e.target.result)
        setWorkflowName(workflow.name || 'Loaded Workflow')
        setNodes(workflow.nodes || [])
        setEdges(workflow.edges || [])
      } catch (error) {
        alert('Error loading workflow file')
        console.error(error)
      }
    }
    reader.readAsText(file)
  }

  return (
    <div className="workflow-builder">
      <div className="workflow-toolbar">
        <input
          type="text"
          value={workflowName}
          onChange={(e) => setWorkflowName(e.target.value)}
          className="workflow-name-input"
          placeholder="Workflow name"
        />
        <div className="toolbar-actions">
          <button onClick={handleRunWorkflow} className="btn btn-primary">
            Run Workflow
          </button>
          <button onClick={handleSaveWorkflow} className="btn btn-secondary">
            Save Workflow
          </button>
          <label className="btn btn-secondary">
            Load Workflow
            <input
              type="file"
              accept=".json"
              onChange={handleLoadWorkflow}
              style={{ display: 'none' }}
            />
          </label>
        </div>
      </div>

      <div className="workflow-canvas">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onNodeClick={onNodeClick}
          onDrop={onDrop}
          onDragOver={onDragOver}
          fitView
        >
          <Controls />
          <MiniMap />
          <Background variant="dots" gap={12} size={1} />
        </ReactFlow>
      </div>
    </div>
  )
}

export default WorkflowBuilder
