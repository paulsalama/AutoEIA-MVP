import { useState } from 'react'
import './FormField.css'

function FormField({ name, schema, value, onChange, required }) {
  const [error, setError] = useState(null)
  const [fileName, setFileName] = useState(null)

  // Format display name from snake_case
  const displayName = name.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())

  const handleNumberChange = (e) => {
    const val = e.target.value
    if (val === '') {
      onChange(null)
    } else {
      onChange(Number(val))
    }
  }

  const handleJsonChange = (e) => {
    const val = e.target.value
    try {
      const parsed = JSON.parse(val)
      onChange(parsed)
      setError(null)
    } catch {
      // Keep as string while editing, show error
      onChange(val)
      if (val.trim()) {
        setError('Invalid JSON')
      } else {
        setError(null)
      }
    }
  }

  const handleFileChange = (e) => {
    const file = e.target.files[0]
    if (file) {
      setFileName(file.name)
      const reader = new FileReader()
      reader.onload = (event) => {
        try {
          const geojson = JSON.parse(event.target.result)
          onChange(geojson)
          setError(null)
        } catch {
          setError('Invalid GeoJSON file')
          onChange(null)
        }
      }
      reader.onerror = () => {
        setError('Error reading file')
        onChange(null)
      }
      reader.readAsText(file)
    }
  }

  const renderInput = () => {
    switch (schema.type) {
      case 'number':
        return (
          <input
            type="number"
            value={value ?? ''}
            onChange={handleNumberChange}
            className="form-input"
            placeholder={schema.default !== undefined ? `Default: ${schema.default}` : ''}
          />
        )

      case 'string':
        return (
          <input
            type="text"
            value={value ?? ''}
            onChange={(e) => onChange(e.target.value || null)}
            className="form-input"
            placeholder={schema.default || ''}
          />
        )

      case 'enum': {
        const enumOptions = schema.enum ?? schema.options ?? []
        return (
          <select
            value={value ?? ''}
            onChange={(e) => onChange(e.target.value || null)}
            className="form-select"
          >
            <option value="">Select...</option>
            {enumOptions.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        )
      }

      case 'boolean':
        return (
          <label className="toggle-label">
            <input
              type="checkbox"
              checked={value ?? false}
              onChange={(e) => onChange(e.target.checked)}
              className="toggle-input"
            />
            <span className="toggle-switch"></span>
            <span className="toggle-text">{value ? 'Yes' : 'No'}</span>
          </label>
        )

      case 'array':
        return (
          <textarea
            value={typeof value === 'string' ? value : (value ? JSON.stringify(value, null, 2) : '')}
            onChange={handleJsonChange}
            className="form-textarea"
            rows={4}
            placeholder='["value1", "value2"]'
          />
        )

      case 'object':
        return (
          <textarea
            value={typeof value === 'string' ? value : (value ? JSON.stringify(value, null, 2) : '')}
            onChange={handleJsonChange}
            className="form-textarea"
            rows={4}
            placeholder='{"key": "value"}'
          />
        )

      case 'geojson':
        return (
          <div className="file-upload">
            <label className="file-upload-label">
              <input
                type="file"
                accept=".geojson,.json"
                onChange={handleFileChange}
                className="file-input"
              />
              <span className="file-button">Choose File</span>
              <span className="file-name">
                {fileName || (value ? 'File loaded' : 'No file selected')}
              </span>
            </label>
            {value && !fileName && (
              <button
                type="button"
                className="clear-file-btn"
                onClick={() => {
                  onChange(null)
                  setFileName(null)
                }}
              >
                Clear
              </button>
            )}
          </div>
        )

      case 'obj': {
        const handleObjFileChange = (e) => {
          const file = e.target.files[0]
          if (file) {
            setFileName(file.name)
            const reader = new FileReader()
            reader.onload = (event) => {
              const text = event.target.result
              if (!text.includes('\nv ') && !text.startsWith('v ')) {
                setError('File does not appear to be a valid OBJ (no vertices found)')
                onChange(null)
              } else {
                onChange(text)
                setError(null)
              }
            }
            reader.onerror = () => { setError('Error reading file'); onChange(null) }
            reader.readAsText(file)
          }
        }
        return (
          <div className="file-upload">
            <label className="file-upload-label">
              <input
                type="file"
                accept=".obj"
                onChange={handleObjFileChange}
                className="file-input"
              />
              <span className="file-button">Choose .obj File</span>
              <span className="file-name">
                {fileName || (value ? 'Model loaded' : 'No file selected')}
              </span>
            </label>
            {value && (
              <button
                type="button"
                className="clear-file-btn"
                onClick={() => { onChange(null); setFileName(null) }}
              >
                Clear
              </button>
            )}
          </div>
        )
      }

      case 'multiselect': {
        const selected = Array.isArray(value) ? value : []
        return (
          <div className="checkbox-group">
            {schema.options?.map(option => {
              const label = option.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
              return (
                <label key={option} className="checkbox-item">
                  <input
                    type="checkbox"
                    checked={selected.includes(option)}
                    onChange={(e) => {
                      const next = e.target.checked
                        ? [...selected, option]
                        : selected.filter(o => o !== option)
                      onChange(next.length ? next : null)
                    }}
                  />
                  <span>{label}</span>
                </label>
              )
            })}
          </div>
        )
      }

      case 'text':
        return (
          <textarea
            value={value ?? ''}
            onChange={(e) => onChange(e.target.value || null)}
            className="form-textarea"
            rows={4}
            placeholder={schema.default || ''}
          />
        )

      default:
        return (
          <input
            type="text"
            value={value ?? ''}
            onChange={(e) => onChange(e.target.value || null)}
            className="form-input"
          />
        )
    }
  }

  return (
    <div className={`form-field ${required ? 'required' : 'optional'} ${error ? 'has-error' : ''}`}>
      <label className="field-label">
        {displayName}
        {required && <span className="required-marker">*</span>}
      </label>
      <p className="field-description">{schema.description}</p>
      {renderInput()}
      {error && <span className="field-error">{error}</span>}
    </div>
  )
}

export default FormField
