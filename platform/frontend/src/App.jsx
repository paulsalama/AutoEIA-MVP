import { useState, useCallback, useRef } from 'react'
import WorkflowBuilder from './components/WorkflowBuilder'
import ModuleSidebar from './components/ModuleSidebar'
import NodeConfigPanel from './components/NodeConfigPanel'
import OutputVisualizationPanel from './components/OutputVisualizationPanel'
import './App.css'

function App() {
  const [selectedNode, setSelectedNode] = useState(null)
  const [workflowResults, setWorkflowResults] = useState(null)
  const [isExecuting, setIsExecuting] = useState(false)
  const [workflowNodes, setWorkflowNodes] = useState([])
  const workflowBuilderRef = useRef(null)

  const handleNodeSelect = useCallback((node) => setSelectedNode(node), [])
  const handleCloseConfigPanel = useCallback(() => setSelectedNode(null), [])
  const handleCloseResultsPanel = useCallback(() => setWorkflowResults(null), [])

  const handleWorkflowStart = useCallback(() => {
    setIsExecuting(true)
    setWorkflowResults(null)
  }, [])

  const handleWorkflowComplete = useCallback((results, nodes) => {
    setWorkflowResults(results)
    setWorkflowNodes(nodes)
    setIsExecuting(false)
    setSelectedNode(null)  // switch right panel to results
  }, [])

  const handleUpdateNodeConfig = useCallback((nodeId, configuredInputs) => {
    if (workflowBuilderRef.current?.updateNodeConfig) {
      workflowBuilderRef.current.updateNodeConfig(nodeId, configuredInputs)
      setSelectedNode(prev => {
        if (prev && prev.id === nodeId) {
          return { ...prev, data: { ...prev.data, configuredInputs } }
        }
        return prev
      })
    }
  }, [])

  // Right panel: results take priority; fall back to node config
  const rightPanel = workflowResults ? (
    <OutputVisualizationPanel
      results={workflowResults}
      nodes={workflowNodes}
      onClose={handleCloseResultsPanel}
    />
  ) : selectedNode ? (
    <NodeConfigPanel
      selectedNode={selectedNode}
      onUpdateNodeConfig={handleUpdateNodeConfig}
      onClose={handleCloseConfigPanel}
    />
  ) : null

  return (
    <div className="app-container">
      <header className="app-header">
        <h1>AutoEIA Module Orchestration Platform</h1>
        <p>Visual Workflow Platform for Environmental Impact Analysis</p>
      </header>
      <div className="app-main">
        <ModuleSidebar />
        <div className="center-area">
          <WorkflowBuilder
            ref={workflowBuilderRef}
            selectedNode={selectedNode}
            onNodeSelect={handleNodeSelect}
            onWorkflowStart={handleWorkflowStart}
            onWorkflowComplete={handleWorkflowComplete}
            isExecuting={isExecuting}
          />
        </div>
        {rightPanel}
      </div>
    </div>
  )
}

export default App
