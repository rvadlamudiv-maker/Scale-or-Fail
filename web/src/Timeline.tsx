// Live graphs under the canvas: traffic, end-to-end latency and requests OK over the whole run,
// drawn up to "now", plus a scrubber with the chaos events marked on it.
import { useMemo } from 'react'
import type { RunResult } from './engine/client'

type Run = Extract<RunResult, { ok: true }>

type ChartProps = {
  title: string
  values: number[]
  now: number
  max: number
  threshold?: number // a dashed target line, e.g. the latency goal
  current: string
  currentClass: string
}

function Chart({ title, values, now, max, threshold, current, currentClass }: ChartProps) {
  const y = (v: number) => 100 - (Math.min(v, max) / max) * 100
  const points = (to: number) => values.slice(0, to + 1).map((v, i) => `${i},${y(v)}`).join(' ')
  const last = values.length - 1
  return (
    <figure className="chart">
      <figcaption>
        <span>{title}</span>
        <b className={currentClass}>{current}</b>
      </figcaption>
      <svg viewBox={`0 0 ${last} 100`} preserveAspectRatio="none" aria-hidden="true">
        {threshold !== undefined && (
          <line className="chart__threshold" x1={0} x2={last} y1={y(threshold)} y2={y(threshold)} vectorEffect="non-scaling-stroke" />
        )}
        <polyline className="chart__ahead" points={points(last)} vectorEffect="non-scaling-stroke" />
        <polyline className="chart__played" points={points(now)} vectorEffect="non-scaling-stroke" />
        <line className="chart__now" x1={now} x2={now} y1={0} y2={100} vectorEffect="non-scaling-stroke" />
      </svg>
    </figure>
  )
}

export function Timeline({ run, index, onSeek }: { run: Run; index: number; onSeek: (tick: number) => void }) {
  const series = useMemo(
    () => ({
      traffic: run.ticks.map((t) => t.nodes[run.client_id]?.served ?? 0),
      latency: run.ticks.map((t) => t.e2e_ms),
      ok: run.ticks.map((t) => t.ok * 100),
    }),
    [run],
  )
  const frame = run.ticks[index]
  const last = run.ticks.length - 1
  const secondsPerTick = last > 0 ? run.ticks[1].t - run.ticks[0].t : 0.1
  const latencyCeiling = Math.max(run.goals.p99_ms * 2, ...series.latency)
  const okClass = frame.ok >= run.goals.availability ? 'is-good' : frame.ok >= 0.95 ? 'is-warn' : 'is-bad'
  const latencyClass = frame.e2e_ms <= run.goals.p99_ms ? 'is-good' : frame.e2e_ms <= run.goals.p99_ms * 2 ? 'is-warn' : 'is-bad'

  return (
    <section className="timeline" aria-label="Timeline">
      <div className="timeline__charts">
        <Chart
          title="Traffic"
          values={series.traffic}
          now={index}
          max={Math.max(...series.traffic) * 1.1 || 1}
          current={`${Math.round(series.traffic[index]).toLocaleString()} rps`}
          currentClass=""
        />
        <Chart
          title="End-to-end latency"
          values={series.latency}
          now={index}
          max={latencyCeiling}
          threshold={run.goals.p99_ms}
          current={`${Math.round(frame.e2e_ms).toLocaleString()} ms`}
          currentClass={latencyClass}
        />
        <Chart
          title="Requests OK"
          values={series.ok}
          now={index}
          max={100}
          threshold={run.goals.availability * 100}
          current={`${(frame.ok * 100).toFixed(1)}%`}
          currentClass={okClass}
        />
      </div>
      <div className="timeline__scrubber">
        {run.events.map((e) => (
          <span
            key={`${e.t}-${e.label}`}
            className="timeline__event"
            style={{ left: `${(e.t / secondsPerTick / last) * 100}%` }}
            title={`${e.t.toFixed(0)}s: ${e.label}`}
          >
            ⚡
          </span>
        ))}
        <input
          type="range"
          min={0}
          max={last}
          value={index}
          onChange={(event) => onSeek(Number(event.target.value))}
          aria-label="Scrub through the run"
        />
      </div>
    </section>
  )
}
