// Rules for wiring components, shared by the editor. They mirror the engine's validation
// (engine/models.py), so a design you can draw is a design the engine will accept.
import type { Edge as FlowEdge, Node as FlowNode } from '@xyflow/react'

export function connectionProblem(source: string, target: string, nodes: FlowNode[], edges: FlowEdge[]): string | null {
  if (source === target) return 'A component can’t call itself.'
  const targetNode = nodes.find((n) => n.id === target)
  if ((targetNode?.data as { component?: { type?: string } })?.component?.type === 'client') {
    return 'Nothing can send traffic into the users.'
  }
  if (edges.some((e) => e.source === source && e.target === target)) return 'These two are already connected.'
  // Adding source -> target makes a loop if target can already reach source.
  const reach = [target]
  const seen = new Set<string>()
  while (reach.length) {
    const id = reach.pop()!
    if (id === source) return 'That would create a loop.'
    if (seen.has(id)) continue
    seen.add(id)
    edges.filter((e) => e.source === id).forEach((e) => reach.push(e.target))
  }
  return null
}

export function nextId(base: string, nodes: FlowNode[]): string {
  // app, app_2, app_3, ...
  if (!nodes.some((n) => n.id === base)) return base
  let i = 2
  while (nodes.some((n) => n.id === `${base}_${i}`)) i++
  return `${base}_${i}`
}
