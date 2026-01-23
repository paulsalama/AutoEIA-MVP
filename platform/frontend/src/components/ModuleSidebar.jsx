import { useState, useEffect } from 'react'
import './ModuleSidebar.css'

// Sample module data - will be fetched from backend in production
const sampleModules = [
  {
    name: 'shadow_tier1_screening',
    display_name: 'Shadow Tier 1 Preliminary Screening',
    description: 'Initial geospatial proximity analysis to determine if detailed shadow study is warranted',
    category: 'shadows',
    jurisdiction: ['NYC', 'generic'],
    inputs: {
      building_geojson: {
        type: 'geojson',
        description: 'Building footprint geometry',
        optional: false,
      },
      building_height_ft: {
        type: 'number',
        description: 'Building height in feet',
        optional: false,
      },
      sensitive_sites: {
        type: 'geojson',
        description: 'Layer of sensitive sites (parks, playgrounds, etc.)',
        optional: true,
      },
    },
    outputs: {
      triggered: {
        type: 'boolean',
        description: 'Whether detailed analysis is triggered',
      },
      affected_sites: {
        type: 'geojson',
        description: 'Sites within shadow radius',
      },
      summary_report: {
        type: 'text',
        description: 'Summary of screening results',
      },
      visualization: {
        type: 'image',
        description: 'Map showing buffer and intersected sites',
      },
    },
  },
  {
    name: 'shadow_tier2_detailed',
    display_name: 'Shadow Tier 2 Detailed Analysis',
    description: 'Detailed shadow path calculations for specified dates and times',
    category: 'shadows',
    jurisdiction: ['NYC', 'Boston', 'generic'],
    inputs: {
      building_geojson: {
        type: 'geojson',
        description: 'Building footprint geometry',
        optional: false,
      },
      building_height_ft: {
        type: 'number',
        description: 'Building height in feet',
        optional: false,
      },
      analysis_dates: {
        type: 'array',
        description: 'Dates for shadow analysis',
        optional: false,
      },
      time_range: {
        type: 'object',
        description: 'Time range for analysis',
        optional: false,
      },
    },
    outputs: {
      shadow_geometry: {
        type: 'geojson',
        description: 'Calculated shadow polygons',
      },
      affected_area_sqft: {
        type: 'number',
        description: 'Total affected area in square feet',
      },
      visualization: {
        type: 'image',
        description: 'Shadow path visualization',
      },
    },
  },
]

function ModuleSidebar() {
  const [modules, setModules] = useState(sampleModules)
  const [searchTerm, setSearchTerm] = useState('')
  const [selectedCategory, setSelectedCategory] = useState('all')

  const categories = ['all', ...new Set(modules.map((m) => m.category))]

  const filteredModules = modules.filter((module) => {
    const matchesSearch =
      module.display_name.toLowerCase().includes(searchTerm.toLowerCase()) ||
      module.description.toLowerCase().includes(searchTerm.toLowerCase())
    const matchesCategory =
      selectedCategory === 'all' || module.category === selectedCategory
    return matchesSearch && matchesCategory
  })

  const onDragStart = (event, module) => {
    event.dataTransfer.setData('application/reactflow', JSON.stringify(module))
    event.dataTransfer.effectAllowed = 'move'
  }

  return (
    <div className="module-sidebar">
      <div className="sidebar-header">
        <h2>Module Library</h2>
        <p className="module-count">{filteredModules.length} modules</p>
      </div>

      <div className="sidebar-filters">
        <input
          type="text"
          placeholder="Search modules..."
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          className="search-input"
        />

        <select
          value={selectedCategory}
          onChange={(e) => setSelectedCategory(e.target.value)}
          className="category-select"
        >
          {categories.map((cat) => (
            <option key={cat} value={cat}>
              {cat.charAt(0).toUpperCase() + cat.slice(1)}
            </option>
          ))}
        </select>
      </div>

      <div className="module-list">
        {filteredModules.map((module) => (
          <div
            key={module.name}
            className="module-card"
            draggable
            onDragStart={(e) => onDragStart(e, module)}
          >
            <div className="module-header">
              <h3>{module.display_name}</h3>
              <span className="module-category">{module.category}</span>
            </div>
            <p className="module-description">{module.description}</p>
            <div className="module-meta">
              <span className="meta-item">
                Inputs: {Object.keys(module.inputs).length}
              </span>
              <span className="meta-item">
                Outputs: {Object.keys(module.outputs).length}
              </span>
            </div>
            <div className="module-jurisdictions">
              {module.jurisdiction.map((j) => (
                <span key={j} className="jurisdiction-tag">
                  {j}
                </span>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

export default ModuleSidebar
