// The simulation frame currently being replayed, shared with every component box.
import { createContext } from 'react'
import type { NodeState } from './engine/client'

export type LiveFrame = { nodes: Record<string, NodeState> } | null

export const LiveContext = createContext<LiveFrame>(null)

export type Health = 'healthy' | 'warning' | 'critical' | 'down'

// The same thresholds as the CLI: over 80% busy is a warning, over 100% is on fire.
export function health(state: NodeState | undefined): Health | null {
  if (!state) return null
  if (state.instances === 0 && state.load > 0) return 'down'
  if (state.load > 1 || state.failed > 0) return 'critical'
  if (state.load > 0.8) return 'warning'
  return 'healthy'
}
