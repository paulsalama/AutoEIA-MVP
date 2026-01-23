import { useState } from 'react'
import WorkflowBuilder from './components/WorkflowBuilder'
import ModuleSidebar from './components/ModuleSidebar'
import './App.css'

function App() {
  const [selectedNode, setSelectedNode] = useState(null)

  return (
    <div className="app-container">
      <header className="app-header">
        <h1>AutoEIA Module Orchestration Platform</h1>
        <p>Visual Workflow Platform for Environmental Impact Analysis</p>
      </header>

      <div className="app-main">
        <ModuleSidebar />
        <WorkflowBuilder
          selectedNode={selectedNode}
          onNodeSelect={setSelectedNode}
        />
      </div>
    </div>
  )
}

export default App
