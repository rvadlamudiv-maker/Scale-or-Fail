import {
  addEdge,
  Background,
  Controls,
  MarkerType,
  ReactFlow,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
  useReactFlow,
  type Connection,
  type Edge as FlowEdge,
  type Node as FlowNode,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { useCallback, useState, type DragEvent } from 'react'
import { ComponentNode } from './ComponentNode'
import { designOptions, parseDesign, type Component, type ComponentType } from './design'
import { connectionProblem, nextId } from './graph'
import { toFlow } from './layout'
import { DRAG_FORMAT, Palette, PALETTE } from './Palette'

// Tell React Flow to draw nodes of type 'component' with our own component.
const nodeTypes = { component: ComponentNode }

function Editor({ initial }: { initial: { nodes: FlowNode[]; edges: FlowEdge[] } }) {
  const [nodes, setNodes, onNodesChange] = useNodesState(initial.nodes)
  const [edges, setEdges, onEdgesChange] = useEdgesState(initial.edges)
  const [problem, setProblem] = useState<string | null>(null)
  const { screenToFlowPosition } = useReactFlow()

  const onConnect = useCallback(
    (c: Connection) => {
      const why = connectionProblem(c.source, c.target, nodes, edges)
      if (why) {
        // Explain why the wire was refused, then clear the message after a few seconds.
        setProblem(why)
        window.setTimeout(() => setProblem(null), 3000)
        return
      }
      setEdges((current) =>
        addEdge(
          {
            ...c,
            id: `${c.source}->${c.target}`,
            animated: true,
            markerEnd: { type: MarkerType.ArrowClosed },
            data: { edge: { source: c.source, target: c.target } },
          },
          current,
        ),
      )
    },
    [nodes, edges, setEdges],
  )

  const onDrop = useCallback(
    (event: DragEvent) => {
      event.preventDefault()
      const type = event.dataTransfer.getData(DRAG_FORMAT) as ComponentType
      const item = PALETTE.find((p) => p.type === type)
      if (!item) return
      const id = nextId(item.idBase, nodes)
      const component: Component = { id, type, instances: type === 'app_server' ? 4 : 1 }
      if (type === 'replica') {
        // A replica must copy a database: start with the first one on the canvas.
        const db = nodes.find((n) => (n.data as { component: Component }).component.type === 'database')
        if (db) component.replica_of = db.id
      }
      const position = screenToFlowPosition({ x: event.clientX, y: event.clientY })
      setNodes((current) => [...current, { id, type: 'component', position, data: { component } }])
    },
    [nodes, screenToFlowPosition, setNodes],
  )

  return (
    <div className="editor">
      <Palette />
      <div
        className="editor__canvas"
        onDragOver={(event) => {
          event.preventDefault()
          event.dataTransfer.dropEffect = 'move'
        }}
        onDrop={onDrop}
      >
        <ReactFlow
          nodeTypes={nodeTypes}
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          fitView
        >
          <Background />
          <Controls />
        </ReactFlow>
        {problem && (
          <div className="editor__problem" role="status">
            {problem}
          </div>
        )}
      </div>
    </div>
  )
}

export default function App() {
  const [selected, setSelected] = useState(0)
  const initial = toFlow(parseDesign(designOptions[selected].yaml))

  return (
    <div className="app">
      <header className="app__header">
        <span className="app__title">Scale or Fail</span>
        <label className="app__picker">
          Start from
          <select value={selected} onChange={(e) => setSelected(Number(e.target.value))}>
            {designOptions.map((option, i) => (
              <option key={option.label} value={i}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      </header>
      {/* key={selected} gives each design a fresh editor */}
      <ReactFlowProvider key={selected}>
        <Editor initial={initial} />
      </ReactFlowProvider>
    </div>
  )
}
