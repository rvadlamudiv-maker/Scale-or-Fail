// The page's side of the engine worker: start it once, send runs, get results back.

export type ScoreLine = { label: string; detail: string; points: number }

export type NodeState = {
  load: number
  served: number
  failed: number
  latency_ms: number
  queue: number
  instances: number
}

export type RunResult =
  | {
      ok: true
      scenario: string
      client_id: string
      goals: { availability: number; p99_ms: number }
      incident: {
        title: string
        date: string
        postmortem_url: string
        summary: string
        real_fixes: string[]
      } | null
      score: { total: number; grade: string; lines: ScoreLine[] }
      metrics: {
        availability: number
        p50_ms: number
        p99_ms: number
        cost_per_hour: number
        freshness: number
        diverged_writes: number
      }
      events: { t: number; label: string }[]
      ticks: { t: number; ok: number; e2e_ms: number; nodes: Record<string, NodeState> }[]
    }
  | { ok: false; error: string }

const worker = new Worker(new URL('./worker.ts', import.meta.url), { type: 'module' })
const waiting = new Map<number, (result: RunResult) => void>()
const statusListeners = new Set<(status: string) => void>()
let status = 'Starting…'
let nextId = 1

worker.onmessage = (event) => {
  const message = event.data
  if (message.type === 'status') {
    status = message.status
    statusListeners.forEach((listener) => listener(status))
  } else if (message.type === 'result') {
    waiting.get(message.id)?.(message.result)
    waiting.delete(message.id)
  }
}

export function engineStatus() {
  return status
}

export function onEngineStatus(listener: (status: string) => void) {
  statusListeners.add(listener)
  return () => {
    statusListeners.delete(listener)
  }
}

export function runSimulation(designYaml: string, scenarioYaml: string): Promise<RunResult> {
  const id = nextId++
  return new Promise((resolve) => {
    waiting.set(id, resolve)
    worker.postMessage({ id, design: designYaml, scenario: scenarioYaml })
  })
}
