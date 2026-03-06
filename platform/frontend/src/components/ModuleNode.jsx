import { Handle, Position } from 'reactflow'
import './ModuleNode.css'

// Layout constants (must match CSS)
const HEADER_H = 40
const PORT_H = 26
const BODY_PAD = 8

function handleTop(i) {
  return HEADER_H + BODY_PAD + i * PORT_H + PORT_H / 2
}

function ModuleNode({ data }) {
  const moduleData = data.moduleData || {}
  const inputs = Object.entries(moduleData.inputs || {})
  const outputs = Object.entries(moduleData.outputs || {})

  return (
    <div className="module-node">
      <div className="module-node-header">
        {moduleData.emoji && <span className="module-emoji">{moduleData.emoji}</span>}
        <span className="module-name">{moduleData.display_name || 'Module'}</span>
      </div>

      <div className="module-node-body">
        <div className="module-node-col module-node-inputs">
          {inputs.map(([key, schema]) => (
            <div key={key} className="port-row">
              <span className="port-label">{key.replace(/_/g, ' ')}</span>
              <span className={`port-type port-type-${schema.type}`}>{schema.type}</span>
            </div>
          ))}
        </div>
        <div className="module-node-col module-node-outputs">
          {outputs.map(([key, schema]) => (
            <div key={key} className="port-row port-row-out">
              <span className={`port-type port-type-${schema.type}`}>{schema.type}</span>
              <span className="port-label">{key.replace(/_/g, ' ')}</span>
            </div>
          ))}
        </div>
      </div>

      {inputs.map(([key, schema], i) => (
        <Handle
          key={`in-${key}`}
          type="target"
          position={Position.Left}
          id={key}
          style={{ top: handleTop(i) }}
          title={`${key}: ${schema.type}`}
          className={`port-handle port-handle-${schema.type}`}
        />
      ))}

      {outputs.map(([key, schema], i) => (
        <Handle
          key={`out-${key}`}
          type="source"
          position={Position.Right}
          id={key}
          style={{ top: handleTop(i) }}
          title={`${key}: ${schema.type}`}
          className={`port-handle port-handle-${schema.type}`}
        />
      ))}
    </div>
  )
}

export default ModuleNode
