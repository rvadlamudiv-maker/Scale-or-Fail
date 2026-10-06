// The design format, shared with the Python engine (engine/models.py).
// Only the fields the editor needs are typed here; everything else is kept as-is.
import { parse } from 'yaml'

export type ComponentType = 'client' | 'load_balancer' | 'app_server' | 'database' | 'cache' | 'replica'

export interface Component {
  id: string
  type: ComponentType
  instances?: number
  [setting: string]: unknown
}

export interface Edge {
  source: string
  target: string
  calls_per_request?: number
  parallel?: boolean
  retries?: number
  [setting: string]: unknown
}

export interface Design {
  components: Component[]
  edges: Edge[]
}

export function parseDesign(yamlText: string): Design {
  const data = parse(yamlText) as Design
  if (!data || !Array.isArray(data.components) || !Array.isArray(data.edges)) {
    throw new Error('A design needs a list of components and a list of edges.')
  }
  return data
}

// Every design file in the project, bundled in at build time.
const designFiles = import.meta.glob('../../designs/*.yaml', { query: '?raw', import: 'default', eager: true })
const incidentFiles = import.meta.glob('../../incidents/*/starter.yaml', { query: '?raw', import: 'default', eager: true })

export interface DesignOption {
  label: string
  yaml: string
}

export const designOptions: DesignOption[] = [
  ...Object.entries(incidentFiles).map(([path, text]) => ({
    label: `Incident: ${path.split('/').at(-2)} (starter)`,
    yaml: text as string,
  })),
  ...Object.entries(designFiles).map(([path, text]) => ({
    label: `Design: ${path.split('/').at(-1)!.replace('.yaml', '')}`,
    yaml: text as string,
  })),
]
