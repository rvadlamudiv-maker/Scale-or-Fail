// How one component looks on the canvas: an icon, its name, what it is, and how many instances run.
// During a replay it also shows live traffic, and its color shows its health.
import { Handle, Position, type Node, type NodeProps } from '@xyflow/react'
import { useContext } from 'react'
import type { Component, ComponentType } from './design'
import { health, LiveContext } from './live'
import './ComponentNode.css'

export type ComponentNodeData = { component: Component }
export type ComponentNodeType = Node<ComponentNodeData, 'component'>

const KIND: Record<ComponentType, string> = {
  client: 'Users',
  load_balancer: 'Load balancer',
  app_server: 'App server',
  database: 'Database',
  cache: 'Cache',
  replica: 'Read replica',
}

// Simple line icons, drawn on a 24x24 grid.
const ICON: Record<ComponentType, string> = {
  client: 'M4 5h16v11H4z M9 20h6 M12 16v4',
  load_balancer: 'M4 12h6 M10 12l6-6 M10 12l6 6 M16 6h4 M16 18h4',
  app_server: 'M4 4h16v7H4z M4 13h16v7H4z M8 7.5h.01 M8 16.5h.01',
  database: 'M5 6c0-1.7 3.1-3 7-3s7 1.3 7 3v12c0 1.7-3.1 3-7 3s-7-1.3-7-3z M5 6c0 1.7 3.1 3 7 3s7-1.3 7-3 M5 12c0 1.7 3.1 3 7 3s7-1.3 7-3',
  cache: 'M13 3L5 14h6l-1 7 8-11h-6l1-7z',
  replica: 'M8 8h12v12H8z M16 8V4H4v12h4',
}

const FLAME = 'M12 2c1.2 3.6 5 6 5 11a5 5 0 0 1-10 0c0-2.4 1.2-3.8 2.4-5 0 2.4 1.2 3.6 2.4 3.6 0-3.6-1.2-6 .2-9.6z'

const fmt = (n: number) => Math.round(n).toLocaleString()

export function ComponentNode({ data, selected }: NodeProps<ComponentNodeType>) {
  const c = data.component
  const live = useContext(LiveContext)?.nodes[c.id]
  const state = c.type === 'client' ? null : health(live)
  const onFire = state === 'critical' || state === 'down'
  const instances = live?.instances ?? c.instances ?? 1
  const autoscales = typeof c.max_instances === 'number'

  const classes = ['component-node', selected && 'is-selected', state && `is-${state}`].filter(Boolean).join(' ')
  return (
    <div className={classes}>
      {c.type !== 'client' && <Handle type="target" position={Position.Left} />}
      <svg className={`component-node__icon${onFire ? ' is-flame' : ''}`} viewBox="0 0 24 24" aria-hidden="true">
        <path d={onFire ? FLAME : ICON[c.type]} />
      </svg>
      <div className="component-node__text">
        <span className="component-node__name">{c.id}</span>
        {live ? (
          <>
            <span className="component-node__live">
              {fmt(live.served)} rps{c.type !== 'client' && ` · ${Math.round(live.load * 100)}%`}
            </span>
            {live.failed > 0 && <span className="component-node__failed">−{fmt(live.failed)} rps failing</span>}
          </>
        ) : (
          <span className="component-node__kind">{KIND[c.type]}</span>
        )}
      </div>
      {c.type !== 'client' && (
        <span className="component-node__count" title={autoscales ? 'Autoscales' : 'Instances'}>
          ×{instances}
          {autoscales && !live && `–${c.max_instances}`}
        </span>
      )}
      <Handle type="source" position={Position.Right} />
    </div>
  )
}
