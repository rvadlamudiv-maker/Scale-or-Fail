// Turn a design into React Flow nodes and edges, laid out left to right.
// Designs don't store positions, so each component's column is how many hops it is from the client.
import { MarkerType, type Edge as FlowEdge, type Node as FlowNode } from '@xyflow/react'
import type { Component, Design, Edge } from './design'

const COLUMN_WIDTH = 320
const ROW_HEIGHT = 110

// A small arrowhead in canvas pixels, so it stays the same size however thick the wire gets.
export const ARROW = { type: MarkerType.ArrowClosed, width: 14, height: 14, markerUnits: 'userSpaceOnUse', color: '#5a6878' } as const

function columns(design: Design): Map<string, number> {
  // Longest path from the client: a component sits one column right of its furthest caller.
  const column = new Map<string, number>(design.components.map((c) => [c.id, 0]))
  for (let pass = 0; pass < design.components.length; pass++) {
    for (const e of design.edges) {
      column.set(e.target, Math.max(column.get(e.target)!, column.get(e.source)! + 1))
    }
  }
  return column
}

export function nodeLabel(c: Component): string {
  const count = c.instances && c.instances > 1 ? ` ×${c.instances}` : ''
  return `${c.id}${count}`
}

export function edgeLabel(e: Edge): string | undefined {
  const parts: string[] = []
  if (e.calls_per_request && e.calls_per_request !== 1) parts.push(`${e.parallel ? '∥' : '×'}${e.calls_per_request}`)
  if (e.retries) parts.push(`↻${e.retries}`)
  return parts.length ? parts.join('  ') : undefined
}

export function toFlow(design: Design): { nodes: FlowNode[]; edges: FlowEdge[] } {
  const column = columns(design)
  const rowsUsed = new Map<number, number>()
  const nodes: FlowNode[] = design.components.map((c) => {
    const col = column.get(c.id)!
    const row = rowsUsed.get(col) ?? 0
    rowsUsed.set(col, row + 1)
    return {
      id: c.id,
      type: 'component',
      position: { x: col * COLUMN_WIDTH, y: row * ROW_HEIGHT },
      data: { component: c },
    }
  })
  const edges: FlowEdge[] = design.edges.map((e) => ({
    id: `${e.source}->${e.target}`,
    type: 'traffic',
    source: e.source,
    target: e.target,
    label: edgeLabel(e),
    animated: true,
    markerEnd: ARROW,
    data: { edge: e },
  }))
  return { nodes, edges }
}
