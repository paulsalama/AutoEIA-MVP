import { useState, useEffect } from 'react'
import axios from 'axios'
import './ModuleSidebar.css'

const API_BASE_URL = 'http://localhost:8000'

function ModuleSidebar() {
  const [modules, setModules] = useState([])
  const [searchTerm, setSearchTerm] = useState('')
  const [selectedCategory, setSelectedCategory] = useState('all')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  // Fetch modules from backend
  useEffect(() => {
    const fetchModules = async () => {
      try {
        setLoading(true)
        const response = await axios.get(`${API_BASE_URL}/api/modules`)
        setModules(response.data.modules || [])
        setError(null)
      } catch (err) {
        console.error('Failed to fetch modules:', err)
        setError('Failed to load modules')
      } finally {
        setLoading(false)
      }
    }

    fetchModules()
  }, [])

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
        {loading && <div className="loading-state">Loading modules...</div>}
        {error && <div className="error-state">{error}</div>}
        {!loading && !error && filteredModules.length === 0 && (
          <div className="empty-state">No modules found</div>
        )}
        {filteredModules.map((module) => (
          <div
            key={module.name}
            className="module-card"
            draggable
            onDragStart={(e) => onDragStart(e, module)}
          >
            {module.emoji && (
              <div className="module-emoji">{module.emoji}</div>
            )}
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
