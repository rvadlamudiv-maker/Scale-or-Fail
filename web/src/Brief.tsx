// The mission brief: what's about to happen and what you're graded on, before you build.
// It reads the scenario YAML directly, so every scenario gets a brief with no extra work.
import { useState } from 'react'
import { parse } from 'yaml'

type Spike = { at_s: number; duration_s: number; multiplier: number }
type Event = { at_s: number; kind: string; target: string; count?: number; factor?: number; duration_s?: number }
type ScenarioDoc = {
  name: string
  description: string
  hint?: string
  duration_s: number
  traffic: { base_rps: number; spikes?: Spike[] }
  goals?: { availability?: number; p99_ms?: number; budget_per_hour?: number }
  events?: Event[]
  incident?: { title: string; date: string }
}

const secs = (s: number) => `${Number.isInteger(s) ? s : s.toFixed(1)}s`

// The same wording as the engine's event labels, written as a forecast.
function forecastEvent(e: Event): string {
  const lasting = e.duration_s ? ` for ${secs(e.duration_s)}` : ''
  switch (e.kind) {
    case 'kill_instances':
      return `${e.count ?? 1} ${e.target} instance(s) die`
    case 'cache_flush':
      return `the ${e.target} cache is wiped`
    case 'slow_down':
      return `${e.target} gets ${e.factor}x slower${lasting}`
    case 'gray_failure':
      return `${e.count ?? 1} ${e.target} instance(s) get ${e.factor}x slower but keep passing health checks${lasting}`
    case 'bad_deploy':
      return `a bad change ships to ${e.target}`
    case 'network_partition':
      return `${e.target} is cut off from its failover automation${lasting}`
    default:
      return `${e.kind} hits ${e.target}`
  }
}

function timeline(doc: ScenarioDoc): { at: number; text: string }[] {
  const items = [{ at: 0, text: `traffic starts at ${doc.traffic.base_rps.toLocaleString()} requests/second` }]
  for (const s of doc.traffic.spikes ?? []) {
    items.push({ at: s.at_s, text: `traffic jumps ${s.multiplier}x for ${secs(s.duration_s)}` })
  }
  for (const e of doc.events ?? []) items.push({ at: e.at_s, text: forecastEvent(e) })
  return items.sort((a, b) => a.at - b.at)
}

type Props = { scenarioYaml: string; eyebrow: string; onClose: () => void }

export function Brief({ scenarioYaml, eyebrow, onClose }: Props) {
  const [showHint, setShowHint] = useState(false)
  const doc = parse(scenarioYaml) as ScenarioDoc
  const goals = doc.goals ?? {}

  return (
    <section className="brief" aria-label="Mission brief">
      <p className="brief__eyebrow">{eyebrow}</p>
      <h2 className="brief__title">{doc.name}</h2>
      <p className="brief__description">{doc.description}</p>
      {doc.incident && (
        <p className="brief__inspired">
          Inspired by the {doc.incident.title} ({doc.incident.date}).
        </p>
      )}

      <h3>What will happen ({secs(doc.duration_s)})</h3>
      <ul className="brief__timeline">
        {timeline(doc).map((item) => (
          <li key={`${item.at}-${item.text}`}>
            <span>{secs(item.at)}</span> {item.text}
          </li>
        ))}
      </ul>

      <h3>Your targets</h3>
      <ul className="brief__goals">
        {goals.availability !== undefined && (
          <li>
            Availability <b>≥ {(goals.availability * 100).toFixed(1)}%</b>
          </li>
        )}
        {goals.p99_ms !== undefined && (
          <li>
            p99 latency <b>≤ {goals.p99_ms.toLocaleString()} ms</b>
          </li>
        )}
        {goals.budget_per_hour !== undefined && (
          <li>
            Budget <b>≤ ${goals.budget_per_hour.toLocaleString()}/hr</b>
          </li>
        )}
      </ul>
      <p className="brief__note">The design on the canvas is where you start. It won’t survive as it is.</p>

      {doc.hint &&
        (showHint ? (
          <p className="brief__hint">💡 {doc.hint}</p>
        ) : (
          <button type="button" className="brief__hint-button" onClick={() => setShowHint(true)}>
            Stuck? Show a hint
          </button>
        ))}

      <button type="button" className="brief__start" onClick={onClose}>
        Start building
      </button>
    </section>
  )
}
