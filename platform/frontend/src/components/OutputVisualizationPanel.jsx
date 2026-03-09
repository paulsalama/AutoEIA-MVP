import { useState, useMemo, useEffect } from 'react'
import OutputRenderer from './OutputRenderer'
import './OutputVisualizationPanel.css'

function summarizeValue(v) {
  if (v === null || v === undefined) return 'null'
  if (typeof v === 'boolean') return v ? 'true' : 'false'
  if (typeof v === 'number') return String(v)
  if (typeof v === 'string') return v  // already summarized by backend
  if (typeof v === 'object') return JSON.stringify(v).slice(0, 80)
  return String(v)
}

function InheritedInputs({ inputsUsed, configuredInputs }) {
  const [open, setOpen] = useState(true)
  if (!inputsUsed || Object.keys(inputsUsed).length === 0) return null

  const configured = configuredInputs || {}
  const inherited = Object.entries(inputsUsed).filter(([k]) => !(k in configured))
  const userSet = Object.entries(inputsUsed).filter(([k]) => k in configured)

  if (inherited.length === 0 && userSet.length === 0) return null

  return (
    <div className="inherited-inputs">
      <button className="inherited-toggle" onClick={() => setOpen(o => !o)}>
        <span>{open ? '▾' : '▸'}</span> Inputs received
      </button>
      {open && (
        <div className="inherited-body">
          {inherited.length > 0 && (
            <>
              <div className="inherited-section-label">From workflow</div>
              {inherited.map(([k, v]) => (
                <div key={k} className="inherited-row inherited-upstream">
                  <span className="inherited-key">{k.replace(/_/g, ' ')}</span>
                  <span className="inherited-val">{summarizeValue(v)}</span>
                </div>
              ))}
            </>
          )}
          {userSet.length > 0 && (
            <>
              <div className="inherited-section-label">Configured</div>
              {userSet.map(([k, v]) => (
                <div key={k} className="inherited-row inherited-configured">
                  <span className="inherited-key">{k.replace(/_/g, ' ')}</span>
                  <span className="inherited-val">{summarizeValue(v)}</span>
                </div>
              ))}
            </>
          )}
        </div>
      )}
    </div>
  )
}

function OutputVisualizationPanel({ results, nodes, onClose, selectedNode }) {
  const [selectedNodeId, setSelectedNodeId] = useState(null)

  const nodeResults = useMemo(() => {
    if (!results) return []
    return Object.entries(results).map(([nodeId, result]) => {
      const node = nodes.find(n => n.id === nodeId)
      return {
        nodeId,
        label: node?.data?.moduleData?.display_name || node?.data?.label || nodeId,
        moduleData: node?.data?.moduleData,
        configuredInputs: node?.data?.configuredInputs || {},
        result,
      }
    })
  }, [results, nodes])

  // Auto-select first node on mount/results change
  useEffect(() => {
    if (nodeResults.length > 0) {
      const currentExists = nodeResults.some(nr => nr.nodeId === selectedNodeId)
      if (!selectedNodeId || !currentExists) setSelectedNodeId(nodeResults[0].nodeId)
    }
  }, [nodeResults, selectedNodeId])

  // Switch tab when user clicks a node on the canvas
  useEffect(() => {
    if (selectedNode && nodeResults.some(nr => nr.nodeId === selectedNode.id)) {
      setSelectedNodeId(selectedNode.id)
    }
  }, [selectedNode, nodeResults])

  const currentResult = nodeResults.find(nr => nr.nodeId === selectedNodeId)

  if (!results || Object.keys(results).length === 0) return null

  return (
    <div className="output-panel">
      <div className="output-header">
        <h3>Results</h3>
        <button onClick={onClose} className="control-btn close" title="Close">&#x00D7;</button>
      </div>

      {nodeResults.length > 1 && (
        <div className="node-tabs">
          {nodeResults.map(({ nodeId, label, result }) => (
            <button
              key={nodeId}
              className={`tab ${selectedNodeId === nodeId ? 'active' : ''} ${result.success ? 'success' : 'error'}`}
              onClick={() => setSelectedNodeId(nodeId)}
            >
              <span className="tab-status">{result.success ? '✓' : '✗'}</span>
              <span className="tab-label">{label}</span>
            </button>
          ))}
        </div>
      )}

      <div className="output-content">
        {currentResult && (
          currentResult.result.success ? (
            <>
              <InheritedInputs
                inputsUsed={currentResult.result.inputs_used}
                configuredInputs={currentResult.configuredInputs}
              />
              <OutputRenderer
                output={currentResult.result.output}
                moduleMetadata={currentResult.moduleData}
              />
            </>
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
