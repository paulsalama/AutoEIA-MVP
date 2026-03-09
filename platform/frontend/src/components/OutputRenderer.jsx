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

  // Extract names from GeoJSON features (tries common name fields)
  const extractFeatureNames = (geojson) => {
    const features = geojson?.features || (geojson?.type === 'Feature' ? [geojson] : [])
    if (features.length === 0) return []
    const nameFields = ['signname', 'propname', 'name', 'display_name', 'title', 'site_name']
    const nameField = nameFields.find(f => f in (features[0]?.properties || {}))
    if (!nameField) return []
    return [...new Set(features.map(f => f.properties[nameField]).filter(Boolean))]
  }

  const renderOutputValue = (key, value, schema) => {
    const type = schema?.type || typeof value

    // HTML visualization
    if (typeof value === 'string' && (value.trim().startsWith('<') || value.includes('<!DOCTYPE'))) {
      const openInTab = () => {
        const w = window.open()
        w.document.write(value)
        w.document.close()
      }
      return (
        <div className="output-item html-output" key={key}>
          <div className="output-label-row">
            <h5 className="output-label">{formatLabel(key)}</h5>
            <button className="open-tab-btn" onClick={openInTab} title="Open map in new tab">
              Open full map
            </button>
          </div>
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

      case 'geojson': {
        const count = countFeatures(value)
        const names = extractFeatureNames(value)
        const SHOW_MAX = 12
        return (
          <div className="output-item geojson-output" key={key}>
            <h5 className="output-label">{formatLabel(key)}</h5>
            <span className="geojson-count">{count} feature{count !== 1 ? 's' : ''}</span>
            {names.length > 0 && (
              <div className="geojson-names">
                {names.slice(0, SHOW_MAX).map((n, i) => (
                  <span key={i} className="site-chip">{n}</span>
                ))}
                {names.length > SHOW_MAX && (
                  <span className="site-chip more">+{names.length - SHOW_MAX} more</span>
                )}
              </div>
            )}
          </div>
        )
      }

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

  // Sort outputs: key metrics first, then geojson/text, visualization last
  const sortedEntries = Object.entries(output).sort(([a, av], [b, bv]) => {
    const priority = (key, val) => {
      if (key === 'visualization') return 10
      if (key === 'summary_report') return 8
      if (key === 'shadow_buffer' || key === 'no_shadow_zone') return 6
      const schema = outputSchemas[key]
      const type = schema?.type || (typeof val === 'boolean' ? 'boolean' : typeof val === 'number' ? 'number' : 'other')
      if (type === 'boolean') return 0
      if (type === 'number') return 1
      if (type === 'geojson') return 5
      return 3
    }
    return priority(a, av) - priority(b, bv)
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
