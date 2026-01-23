import './OutputRenderer.css'

function OutputRenderer({ output, moduleMetadata }) {
  const outputSchemas = moduleMetadata?.outputs || {}

  // Helper to format field names
  const formatLabel = (key) => {
    return key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
  }

  // Helper to count GeoJSON features
  const countFeatures = (geojson) => {
    if (geojson?.features) return geojson.features.length
    if (geojson?.type === 'Feature') return 1
    return 0
  }

  const renderOutputValue = (key, value, schema) => {
    const type = schema?.type || typeof value

    // Check if it's HTML visualization (starts with < or contains html/body tags)
    if (typeof value === 'string' && (value.trim().startsWith('<') || value.includes('<!DOCTYPE'))) {
      return (
        <div className="output-item html-output" key={key}>
          <h5 className="output-label">{formatLabel(key)}</h5>
          <iframe
            srcDoc={value}
            title={key}
            className="visualization-iframe"
            sandbox="allow-scripts allow-same-origin"
          />
        </div>
      )
    }

    switch (type) {
      case 'boolean':
        return (
          <div className="output-item boolean-output" key={key}>
            <h5 className="output-label">{formatLabel(key)}</h5>
            <span className={`boolean-badge ${value ? 'true' : 'false'}`}>
              {value ? 'Yes' : 'No'}
            </span>
          </div>
        )

      case 'number':
        return (
          <div className="output-item number-output" key={key}>
            <h5 className="output-label">{formatLabel(key)}</h5>
            <span className="number-value">
              {typeof value === 'number' ? value.toLocaleString() : value}
            </span>
          </div>
        )

      case 'text':
        return (
          <div className="output-item text-output" key={key}>
            <h5 className="output-label">{formatLabel(key)}</h5>
            <pre className="text-content">{value}</pre>
          </div>
        )

      case 'geojson':
        return (
          <div className="output-item geojson-output" key={key}>
            <h5 className="output-label">{formatLabel(key)}</h5>
            <details className="geojson-details">
              <summary>
                View GeoJSON ({countFeatures(value)} feature{countFeatures(value) !== 1 ? 's' : ''})
              </summary>
              <pre className="json-content">{JSON.stringify(value, null, 2)}</pre>
            </details>
          </div>
        )

      case 'image':
        return (
          <div className="output-item image-output" key={key}>
            <h5 className="output-label">{formatLabel(key)}</h5>
            <img src={value} alt={key} className="output-image" />
          </div>
        )

      case 'object':
        return (
          <div className="output-item object-output" key={key}>
            <h5 className="output-label">{formatLabel(key)}</h5>
            <details className="object-details">
              <summary>View Object</summary>
              <pre className="json-content">{JSON.stringify(value, null, 2)}</pre>
            </details>
          </div>
        )

      default:
        // For strings and unknown types
        if (typeof value === 'object' && value !== null) {
          return (
            <div className="output-item json-output" key={key}>
              <h5 className="output-label">{formatLabel(key)}</h5>
              <pre className="json-content">{JSON.stringify(value, null, 2)}</pre>
            </div>
          )
        }
        return (
          <div className="output-item text-output" key={key}>
            <h5 className="output-label">{formatLabel(key)}</h5>
            <span className="text-value">{String(value)}</span>
          </div>
        )
    }
  }

  if (!output || Object.keys(output).length === 0) {
    return <div className="output-empty">No output data</div>
  }

  // Sort outputs: visualization and summary_report last (they're usually larger)
  const sortedEntries = Object.entries(output).sort(([a], [b]) => {
    const priority = { visualization: 2, summary_report: 1 }
    return (priority[a] || 0) - (priority[b] || 0)
  })

  return (
    <div className="output-renderer">
      {sortedEntries.map(([key, value]) =>
        renderOutputValue(key, value, outputSchemas[key])
      )}
    </div>
  )
}

export default OutputRenderer
