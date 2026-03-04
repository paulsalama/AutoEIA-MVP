import { useCallback, useState, forwardRef, useImperativeHandle } from 'react'
import ReactFlow, {
  Controls,
  Background,
  useNodesState,
  useEdgesState,
  addEdge,
  MarkerType,
} from 'reactflow'
import axios from 'axios'
import 'reactflow/dist/style.css'
import './WorkflowBuilder.css'

const initialNodes = []
const initialEdges = []

const API_BASE_URL = 'http://localhost:8000'

const WorkflowBuilder = forwardRef(function WorkflowBuilder(
  { selectedNode, onNodeSelect, onWorkflowStart, onWorkflowComplete, isExecuting },
  ref
) {
  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes)
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges)
  const [workflowName, setWorkflowName] = useState('Untitled Workflow')

  // Expose updateNodeConfig to parent via ref
  useImperativeHandle(ref, () => ({
    updateNodeConfig: (nodeId, configuredInputs) => {
      setNodes((nds) =>
        nds.map((node) => {
          if (node.id === nodeId) {
            return {
              ...node,
              className: '',  // clear run state when inputs change
              data: {
                ...node.data,
                configuredInputs,
              },
            }
          }
          return node
        })
      )
    },
  }))

  const onConnect = useCallback(
    (params) => {
      setNodes((nds) => nds.map((n) => ({ ...n, className: '' })))  // clear run states on new connection
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
      )
    },
    [setEdges, setNodes]
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
        sourcePosition: 'right',
        targetPosition: 'left',
        data: {
          label: (moduleData.emoji ? moduleData.emoji + ' ' : '') + moduleData.display_name,
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
    if (nodes.length === 0) {
      alert('Add modules to the workflow before running')
      return
    }

    // Mark all nodes as running
    setNodes((nds) => nds.map((n) => ({ ...n, className: 'node-running' })))

    if (onWorkflowStart) {
      onWorkflowStart()
    }

    try {
      const response = await axios.post(`${API_BASE_URL}/api/workflow/execute`, {
        name: workflowName,
        nodes: nodes,
        edges: edges,
      })

      if (response.data.success) {
        // Update each node based on its individual result
        setNodes((nds) =>
          nds.map((n) => {
            const r = response.data.results?.[n.id]
            if (!r) return { ...n, className: '' }
            return { ...n, className: r.success ? 'node-done' : 'node-error' }
          })
        )
        if (onWorkflowComplete) {
          onWorkflowComplete(response.data.results, nodes)
        }
      } else {
        setNodes((nds) => nds.map((n) => ({ ...n, className: 'node-error' })))
        alert(`Workflow execution failed: ${response.data.error || 'Check backend logs'}`)
        if (onWorkflowComplete) {
          onWorkflowComplete(null, nodes)
        }
      }
    } catch (error) {
      setNodes((nds) => nds.map((n) => ({ ...n, className: 'node-error' })))
      console.error('Workflow execution error:', error)
      const errorMessage = error.response?.data?.error || error.message
      alert(`Error executing workflow: ${errorMessage}`)
      if (onWorkflowComplete) {
        onWorkflowComplete(null, nodes)
      }
    }
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
          <button
            onClick={handleRunWorkflow}
            className="btn btn-primary"
            disabled={isExecuting}
          >
            {isExecuting ? 'Running...' : 'Run Workflow'}
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
          <Background variant="dots" gap={12} size={1} />
        </ReactFlow>
      </div>
    </div>
  )
})

export default WorkflowBuilder
