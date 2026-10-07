import {
  addEdge,
  Background,
  Controls,
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
import { stringify } from 'yaml'
import { ComponentNode } from './ComponentNode'
import { DEFAULT_SCENARIO, designOptions, parseDesign, scenarioOptions, type Component, type ComponentType } from './design'
import { runSimulation, type RunResult } from './engine/client'
import { designProblems, toDesign } from './exportDesign'
import { ResultsPanel } from './ResultsPanel'
import { RunBar } from './RunBar'
import { connectionProblem, nextId } from './graph'
import { ARROW, toFlow } from './layout'
import { DRAG_FORMAT, Palette, PALETTE } from './Palette'
import { SettingsPanel } from './SettingsPanel'
import { LiveContext } from './live'
import { Playback } from './Playback'
import { useReplay } from './useReplay'
import { TrafficEdge } from './TrafficEdge'
import { Timeline } from './Timeline'
import { loadDaily, recordFrom, saveDaily, todaysDaily, type Daily } from './daily'
import { ShareCard } from './ShareCard'
import { Tour, tutorialSeen } from './Tour'
import { Brief } from './Brief'

// Tell React Flow to draw nodes of type 'component' with our own component.
const nodeTypes = { component: ComponentNode }
const edgeTypes = { traffic: TrafficEdge }

type EditorProps = { initial: { nodes: FlowNode[]; edges: FlowEdge[] }; initialScenario: string; daily: Daily | null }

function Editor({ initial, initialScenario, daily }: EditorProps) {
  const [nodes, setNodes, onNodesChange] = useNodesState(initial.nodes)
  const [edges, setEdges, onEdgesChange] = useEdgesState(initial.edges)
  const [problem, setProblem] = useState<string | null>(null)
  const { screenToFlowPosition } = useReactFlow()
  const [scenario, setScenario] = useState(initialScenario)
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<RunResult | null>(null)
  const [runId, setRunId] = useState(0)
  const [ranDesign, setRanDesign] = useState('') // the design (as YAML) behind the current result
  const design = toDesign(nodes, edges)

  // Daily Outage: today's result, if this browser already played.
  const [record, setRecord] = useState(() => (daily ? loadDaily(daily.key) : null))
  const [shareOpen, setShareOpen] = useState(true)
  // The mission brief opens with every new scenario (unless today's daily is already played).
  const [briefOpen, setBriefOpen] = useState(() => !record)
  const scenarioYamlNow = daily ? daily.scenarioYaml : scenarioOptions.find((s) => s.label === scenario)!.yaml

  const run = async () => {
    const scenarioYaml = daily ? daily.scenarioYaml : scenarioOptions.find((s) => s.label === scenario)!.yaml
    setBriefOpen(false)
    const designYaml = stringify(design)
    setRanDesign(designYaml)
    setRunning(true)
    const outcome = await runSimulation(designYaml, scenarioYaml)
    setResult(outcome)
    setRunId((id) => id + 1)
    setRunning(false)
    if (daily && outcome.ok && !record) {
      const saved = recordFrom(daily, outcome)
      saveDaily(daily.key, saved)
      setRecord(saved)
      setShareOpen(true)
    }
  }

  // Replay the run on the canvas, tick by tick.
  const ticks = result?.ok ? result.ticks : []
  const secondsPerTick = ticks.length > 1 ? ticks[1].t - ticks[0].t : 0.1
  const replay = useReplay(ticks.length, secondsPerTick, runId)
  const frame = ticks[replay.index]
  const recentEvents = result?.ok && frame ? result.events.filter((e) => e.t <= frame.t && e.t > frame.t - 3) : []

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
            type: 'traffic',
            animated: true,
            markerEnd: ARROW,
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
        <LiveContext.Provider value={frame ? { nodes: frame.nodes } : null}>
          <ReactFlow
            nodeTypes={nodeTypes}
            edgeTypes={edgeTypes}
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            fitView
            fitViewOptions={{ padding: 0.15 }}
          >
            <Background />
            <Controls />
          </ReactFlow>
        </LiveContext.Provider>
        <RunBar
          scenario={scenario}
          onScenarioChange={(label) => {
            setScenario(label)
            setBriefOpen(true)
          }}
          onBrief={() => setBriefOpen(true)}
          onRun={run}
          running={running}
          canRun={designProblems(design).length === 0}
          daily={daily ? { label: `Daily Outage #${daily.number}: ${daily.title}`, played: Boolean(record) } : undefined}
        />
        {frame && !replay.done && (
          <Playback
            t={frame.t}
            duration={ticks.at(-1)!.t + secondsPerTick}
            ok={frame.ok}
            e2eMs={frame.e2e_ms}
            latestEvent={recentEvents.at(-1)?.label ?? null}
            playing={replay.playing}
            onPlayPause={() => replay.setPlaying(!replay.playing)}
            speed={replay.speed}
            onSpeed={replay.setSpeed}
            onSkip={replay.skipToEnd}
          />
        )}
        {result?.ok && frame && <Timeline run={result} index={replay.index} onSeek={replay.seek} />}
        {result && (!result.ok || replay.done) && <ResultsPanel result={result} onClose={() => setResult(null)} stale={stringify(design) !== ranDesign} />}
        {briefOpen && (
          <Brief
            scenarioYaml={scenarioYamlNow}
            eyebrow={daily ? `Daily Outage #${daily.number}` : scenario.startsWith('Incident') ? 'Real-outage incident' : 'Practice scenario'}
            onClose={() => setBriefOpen(false)}
          />
        )}
        {daily && record && shareOpen && (!result || replay.done) && (
          <ShareCard record={record} nextNumber={daily.number + 1} onClose={() => setShareOpen(false)} />
        )}
        {problem && (
          <div className="editor__problem" role="status">
            {problem}
          </div>
        )}
      </div>
      <SettingsPanel nodes={nodes} edges={edges} setNodes={setNodes} setEdges={setEdges} />
    </div>
  )
}

// Where today's incident starter sits in the "Start from" list.
const starterIndex = (d: Daily) => designOptions.findIndex((o) => o.label === `Incident: ${d.incident} (starter)`)

export default function App() {
  // Open straight into today's Daily Outage: the first thing anyone sees is a puzzle to solve.
  const [selected, setSelected] = useState(() => starterIndex(todaysDaily()))
  const [daily, setDaily] = useState<Daily | null>(() => todaysDaily())
  const [touring, setTouring] = useState(() => !tutorialSeen()) // first visit: show the walkthrough

  const toggleDaily = () => {
    if (daily) {
      setDaily(null)
      return
    }
    const today = todaysDaily()
    setSelected(starterIndex(today))
    setDaily(today)
  }
  const initial = toFlow(parseDesign(designOptions[selected].yaml))

  return (
    <div className="app">
      <div className="app__small-screen" role="alert">
        <h1>Scale or Fail</h1>
        <p>This game is built for a laptop or desktop screen. Open it on a bigger screen to play.</p>
      </div>
      <header className="app__header">
        <span className="app__title">Scale or Fail</span>
        <button type="button" className={`app__daily${daily ? ' is-active' : ''}`} onClick={toggleDaily}>
          {daily ? 'Leave Daily Outage' : `Daily Outage #${todaysDaily().number}`}
        </button>
        <label className="app__picker">
          Start from
          <select value={selected} disabled={Boolean(daily)} onChange={(e) => setSelected(Number(e.target.value))}>
            {designOptions.map((option, i) => (
              <option key={option.label} value={i}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <button type="button" className="app__help" onClick={() => setTouring(true)}>
          How to play
        </button>
      </header>
      {/* key={selected} gives each design a fresh editor */}
      <ReactFlowProvider key={`${selected}-${daily ? 'daily' : 'free'}`}>
        <Editor initial={initial} initialScenario={designOptions[selected].scenario ?? DEFAULT_SCENARIO} daily={daily} />
      </ReactFlowProvider>
      {touring && <Tour onClose={() => setTouring(false)} />}
    </div>
  )
}
