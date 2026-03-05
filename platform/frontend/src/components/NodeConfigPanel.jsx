import { useMemo, useEffect } from 'react'
import FormField from './FormField'
import './NodeConfigPanel.css'

function NodeConfigPanel({ selectedNode, onUpdateNodeConfig, onClose }) {
  if (!selectedNode) return null

  const moduleData = selectedNode.data?.moduleData
  const configuredInputs = selectedNode.data?.configuredInputs || {}

  // Separate required and optional inputs
  const { requiredInputs, optionalInputs } = useMemo(() => {
    const inputs = moduleData?.inputs || {}
    const required = {}
    const optional = {}

    Object.entries(inputs).forEach(([key, schema]) => {
      if (schema.optional) {
        optional[key] = schema
      } else {
        required[key] = schema
      }
    })

    return { requiredInputs: required, optionalInputs: optional }
  }, [moduleData])

  const missingRequired = Object.keys(requiredInputs).filter((k) => !configuredInputs[k])
  const isReady = missingRequired.length === 0

  // Auto-populate fields based on jurisdiction selection
  useEffect(() => {
    const jurisdiction = configuredInputs.jurisdiction
    if (!jurisdiction || !moduleData?.inputs) return

    const newInputs = { ...configuredInputs }
    let hasChanges = false

    // Check each input for jurisdiction_defaults
    Object.entries(moduleData.inputs).forEach(([fieldName, schema]) => {
      if (fieldName === 'jurisdiction') return // Skip the jurisdiction field itself

      if (schema.jurisdiction_defaults && schema.jurisdiction_defaults[jurisdiction]) {
        // Only auto-populate if the field is empty
        if (!configuredInputs[fieldName]) {
          newInputs[fieldName] = schema.jurisdiction_defaults[jurisdiction]
          hasChanges = true
        }
      }
    })

    if (hasChanges) {
      onUpdateNodeConfig(selectedNode.id, newInputs)
    }
  }, [configuredInputs.jurisdiction, moduleData, selectedNode.id, onUpdateNodeConfig])

  const handleFieldChange = (fieldName, value) => {
    const newInputs = { ...configuredInputs }
    if (value === null || value === undefined || value === '') {
      delete newInputs[fieldName]
    } else {
      newInputs[fieldName] = value
    }
    onUpdateNodeConfig(selectedNode.id, newInputs)
  }

  if (!moduleData) {
    return (
      <div className="node-config-panel">
        <div className="config-header">
          <h3>Configure Node</h3>
          <button onClick={onClose} className="close-btn">&times;</button>
        </div>
        <p className="config-empty">No module data available</p>
      </div>
    )
  }

  return (
    <div className="node-config-panel">
      <div className="config-header">
        <h3>{moduleData.display_name || 'Configure Node'}</h3>
        <span className={isReady ? 'config-status config-status--ready' : 'config-status config-status--missing'}>
          {isReady ? '✓ Ready' : missingRequired.length + ' required'}
        </span>
        <button onClick={onClose} className="close-btn">&times;</button>
      </div>

      <div className="config-body">
        <p className="config-description">{moduleData.description}</p>

        {moduleData.jurisdiction && moduleData.jurisdiction.length > 0 && (
          <div className="jurisdiction-tags">
            {moduleData.jurisdiction.map(j => (
              <span key={j} className="jurisdiction-tag">{j}</span>
            ))}
          </div>
        )}

        {Object.keys(requiredInputs).length > 0 && (
          <div className="config-section">
            <h4>Required Inputs</h4>
            {Object.entries(requiredInputs).map(([name, schema]) => (
              <FormField
                key={name}
                name={name}
                schema={schema}
                value={configuredInputs[name]}
                onChange={(value) => handleFieldChange(name, value)}
                required={true}
              />
            ))}
          </div>
        )}

        {Object.keys(optionalInputs).length > 0 && (
          <div className="config-section">
            <h4>Optional Inputs</h4>
            {Object.entries(optionalInputs).map(([name, schema]) => (
              <FormField
                key={name}
                name={name}
                schema={schema}
                value={configuredInputs[name]}
                onChange={(value) => handleFieldChange(name, value)}
                required={false}
              />
            ))}
          </div>
        )}

        {moduleData.outputs && Object.keys(moduleData.outputs).length > 0 && (
          <div className="config-section outputs-section">
            <h4>Outputs</h4>
            <ul className="outputs-list">
              {Object.entries(moduleData.outputs).map(([name, schema]) => (
                <li key={name}>
                  <span className="output-name">{name.replace(/_/g, ' ')}</span>
                  <span className="output-type">{schema.type}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  )
}

export default NodeConfigPanel
