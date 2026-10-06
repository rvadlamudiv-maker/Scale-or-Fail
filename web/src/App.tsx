import { Background, Controls, ReactFlow } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { useMemo, useState } from 'react'
import { ComponentNode } from './ComponentNode'
import { designOptions, parseDesign } from './design'
import { toFlow } from './layout'

// Tell React Flow to draw nodes of type 'component' with our own component.
const nodeTypes = { component: ComponentNode }

export default function App() {
  const [selected, setSelected] = useState(0)
  const flow = useMemo(() => toFlow(parseDesign(designOptions[selected].yaml)), [selected])

  return (
    <div style={{ width: '100vw', height: '100vh', display: 'flex', flexDirection: 'column' }}>
      <header style={{ padding: 12, borderBottom: '1px solid var(--line)' }}>
        <label>
          Design{' '}
          <select value={selected} onChange={(e) => setSelected(Number(e.target.value))}>
            {designOptions.map((option, i) => (
              <option key={option.label} value={i}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      </header>
      <div style={{ flex: 1 }}>
        {/* key={selected} gives each design a fresh canvas */}
        <ReactFlow key={selected} nodeTypes={nodeTypes} defaultNodes={flow.nodes} defaultEdges={flow.edges} fitView>
          <Background />
          <Controls />
        </ReactFlow>
      </div>
    </div>
  )
}
