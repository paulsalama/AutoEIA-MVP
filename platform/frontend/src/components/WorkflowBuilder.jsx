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


// Trace upstream edges recursively to find all keys that will propagate to nodeId
function computeInheritedKeys(nodeId, nodes, edges) {
  const result = {}  // key -> source module display name
  const visited = new Set()

  function traverse(id) {
    if (visited.has(id)) return
    visited.add(id)
    for (const edge of edges) {
      if (edge.target !== id) continue
      const src = nodes.find((n) => n.id === edge.source)
      if (!src) continue
      const srcName = src.data?.moduleData?.display_name || src.id
      for (const k of Object.keys(src.data?.moduleData?.outputs || {})) {
        if (!(k in result)) result[k] = srcName
      }
      for (const k of Object.keys(src.data?.configuredInputs || {})) {
        if (!(k in result)) result[k] = srcName
      }
      traverse(edge.source)
    }
  }

  traverse(nodeId)
  return result
}

const WorkflowBuilder = forwardRef(function WorkflowBuilder(
  { selectedNode, onNodeSelect, onWorkflowStart, onWorkflowComplete, isExecuting },
  ref
) {
  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes)
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges)
  const [workflowName, setWorkflowName] = useState('Untitled Workflow')

  // Expose updateNodeConfig to parent via ref
  useImperativeHandle(ref, () => ({
deleteNode: (nodeId) => {
      setNodes((nds) => nds.filter((n) => n.id !== nodeId))
      setEdges((eds) => eds.filter((e) => e.source !== nodeId && e.target !== nodeId))
    },
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
            animated: false,
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
      const inheritedKeys = computeInheritedKeys(node.id, nodes, edges)
      onNodeSelect(node, inheritedKeys)
    },
    [onNodeSelect, nodes, edges]
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

    setNodes((nds) => nds.map((n) => ({ ...n, className: 'node-running' })))
    setEdges((eds) => eds.map((e) => ({ ...e, animated: true })))

    if (onWorkflowStart) {
      onWorkflowStart()
    }

    const results = {}

    try {
      const response = await fetch(`${API_BASE_URL}/api/workflow/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: workflowName, nodes, edges }),
      })

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() // keep any incomplete line

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const msg = JSON.parse(line.slice(6))

          if (msg.done) break

          if (msg.error) {
            setEdges((eds) => eds.map((e) => ({ ...e, animated: false })))
            setNodes((nds) => nds.map((n) => ({ ...n, className: 'node-error' })))
            alert(`Workflow error: ${msg.error}`)
            if (onWorkflowComplete) onWorkflowComplete(null, nodes)
            return
          }

          const { node_id, result } = msg
          results[node_id] = result
          if (result.inputs_used) results[node_id].inputs_used = result.inputs_used

          // Update this node immediately as it completes
          setNodes((nds) =>
            nds.map((n) =>
              n.id === node_id
                ? { ...n, className: result.success ? 'node-done' : 'node-error' }
                : n
            )
          )
        }
      }

      setEdges((eds) => eds.map((e) => ({ ...e, animated: false })))
      if (onWorkflowComplete) {
        onWorkflowComplete(results, nodes)
      }
    } catch (error) {
      setEdges((eds) => eds.map((e) => ({ ...e, animated: false })))
      setNodes((nds) => nds.map((n) => ({ ...n, className: 'node-error' })))
      console.error('Workflow execution error:', error)
      alert(`Error executing workflow: ${error.message}`)
      if (onWorkflowComplete) onWorkflowComplete(null, nodes)
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
          deleteKeyCode={["Delete", "Backspace"]}  
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
