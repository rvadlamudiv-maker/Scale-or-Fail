// The scorecard after a run: grade, headline numbers, score lines and what went wrong when.
import type { RunResult } from './engine/client'

const fmt = (n: number) => Math.round(n).toLocaleString()

export function ResultsPanel({ result, onClose }: { result: RunResult; onClose: () => void }) {
  if (!result.ok) {
    return (
      <section className="results results--error" aria-label="Run failed">
        <p>The engine couldn’t run this design: {result.error}</p>
        <button type="button" onClick={onClose}>
          Close
        </button>
      </section>
    )
  }
  const { score, metrics, events, incident } = result
  return (
    <section className="results" aria-label="Results">
      <div className={`results__grade results__grade--${score.grade}`}>{score.grade}</div>
      <div className="results__body">
        <div className="results__headline">
          <span>
            <b>{fmt(score.total)}</b> points
          </span>
          <span>
            availability <b>{(metrics.availability * 100).toFixed(2)}%</b>
          </span>
          <span>
            p99 <b>{fmt(metrics.p99_ms)} ms</b>
          </span>
          <span>
            <b>${fmt(metrics.cost_per_hour)}</b>/hr
          </span>
        </div>
        <ul className="results__lines">
          {score.lines
            .filter((line) => line.label !== 'Base')
            .map((line) => (
              <li key={line.label}>
                <span>{line.label}</span>
                <span className="results__detail">{line.detail}</span>
                <span className={line.points < 0 ? 'is-bad' : line.points > 0 ? 'is-good' : ''}>
                  {line.points > 0 ? '+' : ''}
                  {fmt(line.points)}
                </span>
              </li>
            ))}
        </ul>
        {incident && (
          <div className="results__debrief">
            <h3>What the real engineers did</h3>
            <ul>
              {incident.real_fixes.map((fix) => (
                <li key={fix}>{fix}</li>
              ))}
            </ul>
            <p>
              Inspired by the {incident.title} ({incident.date}).{' '}
              <a href={incident.postmortem_url} target="_blank" rel="noopener noreferrer">
                Read the public postmortem
              </a>
              . A simplified recreation, not affiliated with the company.
            </p>
          </div>
        )}
        {events.length > 0 && (
          <ul className="results__events">
            {events.map((e) => (
              <li key={`${e.t}-${e.label}`}>
                <span>{e.t.toFixed(0)}s</span> {e.label}
              </li>
            ))}
          </ul>
        )}
      </div>
      <button type="button" className="results__close" onClick={onClose} aria-label="Close results">
        ×
      </button>
    </section>
  )
}
