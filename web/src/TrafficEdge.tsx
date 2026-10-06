// A wire that shows traffic during a replay: thicker with more requests, colored by the health
// of the component it feeds, with dots flowing along it (red dots are requests that fail).
import { BaseEdge, getBezierPath, type EdgeProps } from '@xyflow/react'
import { useContext } from 'react'
import type { Edge } from './design'
import { health, LiveContext, type Health } from './live'

const COLOR: Record<Health, string> = {
  healthy: 'var(--healthy)',
  warning: 'var(--warning)',
  critical: 'var(--critical)',
  down: 'var(--critical)',
}

const DOT_TRIP_SECONDS = 1.2

export function TrafficEdge(props: EdgeProps) {
  const { id, source, target, markerEnd, label, data } = props
  const [path, labelX, labelY] = getBezierPath(props)
  const live = useContext(LiveContext)
  const from = live?.nodes[source]
  const to = live?.nodes[target]

  // Not replaying: the plain editor wire.
  if (!from || !to) {
    return <BaseEdge id={id} path={path} markerEnd={markerEnd} label={label} labelX={labelX} labelY={labelY} />
  }

  // Requests per second on this wire: what the caller sent (served x calls per request), but never
  // more than the target received - a cache only passes its misses on, a load balancer splits.
  const edge = (data as { edge?: Edge } | undefined)?.edge
  const sent = from.served * (edge?.calls_per_request ?? 1)
  const attempted = to.served + to.failed
  const rate = Math.min(sent, attempted)
  const state = health(to) ?? 'healthy'
  const color = COLOR[state]
  // Thickness grows with the order of magnitude: 10 rps is thin, 10,000 rps is thick.
  const width = Math.min(7, Math.max(1.5, Math.log10(rate + 1) * 1.5))
  // More traffic, more dots (1-5). The share of red dots matches the share of requests that fail.
  const dots = rate < 1 ? 0 : Math.min(5, Math.max(1, Math.round(Math.log10(rate))))
  const failingDots = attempted > 0 ? Math.round((to.failed / attempted) * dots) : 0

  return (
    <>
      <BaseEdge
        id={id}
        path={path}
        markerEnd={markerEnd}
        label={label}
        labelX={labelX}
        labelY={labelY}
        style={{ stroke: color, strokeWidth: width, strokeDasharray: 'none', animation: 'none', opacity: 0.85 }}
      />
      {Array.from({ length: dots }, (_, i) => (
        <circle key={i} className="traffic-edge__dot" r={3} fill={i < failingDots ? 'var(--critical)' : 'var(--text)'}>
          <animateMotion
            dur={`${DOT_TRIP_SECONDS}s`}
            begin={`${-(i * DOT_TRIP_SECONDS) / dots}s`}
            repeatCount="indefinite"
            path={path}
          />
        </circle>
      ))}
    </>
  )
}
