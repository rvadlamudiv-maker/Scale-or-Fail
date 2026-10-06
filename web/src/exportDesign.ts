// Turn what's on the canvas back into the design format the engine reads.
import type { Edge as FlowEdge, Node as FlowNode } from '@xyflow/react'
import { stringify } from 'yaml'
import type { Component, Design, Edge } from './design'

export function toDesign(nodes: FlowNode[], edges: FlowEdge[]): Design {
  return {
    components: nodes.map((n) => (n.data as { component: Component }).component),
    edges: edges.map((e) => ({ ...((e.data as { edge?: Edge })?.edge ?? {}), source: e.source, target: e.target })),
  }
}

// The same checks the engine makes, in plain words. An empty list means the design will run.
export function designProblems(design: Design): string[] {
  const problems: string[] = []
  const clients = design.components.filter((c) => c.type === 'client')
  if (clients.length !== 1) problems.push('A design needs exactly one Users box.')
  else if (!design.edges.some((e) => e.source === clients[0].id)) problems.push('Wire the Users box to something.')
  const databases = new Set(design.components.filter((c) => c.type === 'database').map((c) => c.id))
  for (const c of design.components) {
    if (c.type === 'replica' && !databases.has(c.replica_of as string)) {
      problems.push(`Pick which database ${c.id} copies.`)
    }
  }
  return problems
}

export function downloadYaml(design: Design, filename = 'my_design.yaml') {
  const blob = new Blob([stringify(design)], { type: 'text/yaml' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}
