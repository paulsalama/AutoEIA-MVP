import { useState, useMemo, useEffect } from 'react'
import OutputRenderer from './OutputRenderer'
import './OutputVisualizationPanel.css'

function OutputVisualizationPanel({ results, nodes, onClose }) {
  const [selectedNodeId, setSelectedNodeId] = useState(null)

  const nodeResults = useMemo(() => {
    if (!results) return []
    return Object.entries(results).map(([nodeId, result]) => {
      const node = nodes.find(n => n.id === nodeId)
      return {
        nodeId,
        label: node?.data?.moduleData?.display_name || node?.data?.label || nodeId,
        moduleData: node?.data?.moduleData,
        result,
      }
    })
  }, [results, nodes])

  useEffect(() => {
    if (nodeResults.length > 0) {
      const currentExists = nodeResults.some(nr => nr.nodeId === selectedNodeId)
      if (!selectedNodeId || !currentExists) setSelectedNodeId(nodeResults[0].nodeId)
    }
  }, [nodeResults, selectedNodeId])

  const currentResult = nodeResults.find(nr => nr.nodeId === selectedNodeId)

  if (!results || Object.keys(results).length === 0) return null

  return (
    <div className="output-panel">
      <div className="output-header">
        <h3>Results</h3>
        <button onClick={onClose} className="control-btn close" title="Close">x</button>
      </div>

      {nodeResults.length > 1 && (
        <div className="node-tabs">
          {nodeResults.map(({ nodeId, label, result }) => (
            <button
              key={nodeId}
              className={`tab ${selectedNodeId === nodeId ? 'active' : ''} ${result.success ? 'success' : 'error'}`}
              onClick={() => setSelectedNodeId(nodeId)}
            >
              <span className="tab-status">{result.success ? 'v' : 'x'}</span>
              <span className="tab-label">{label}</span>
            </button>
          ))}
        </div>
      )}

      <div className="output-content">
        {currentResult && (
          currentResult.result.success ? (
            <OutputRenderer
              output={currentResult.result.output}
              moduleMetadata={currentResult.moduleData}
            />
          ) : (
            <div className="error-display">
              <h4>Execution Error</h4>
              <pre className="error-message">{currentResult.result.error || 'Unknown error'}</pre>
            </div>
          )
        )}
      </div>
    </div>
  )
}

export default OutputVisualizationPanel
