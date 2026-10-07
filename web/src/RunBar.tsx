// Pick a scenario and run the current design through the Python engine.
import { useEffect, useState } from 'react'
import { scenarioOptions } from './design'
import { engineStatus, onEngineStatus } from './engine/client'

type Props = {
  scenario: string
  onScenarioChange: (label: string) => void
  onRun: () => void
  running: boolean
  canRun: boolean
  daily?: { label: string; played: boolean } // Daily Outage: fixed scenario, one attempt
  onBrief: () => void // reopen the mission brief
}

export function RunBar({ scenario, onScenarioChange, onRun, running, canRun, daily, onBrief }: Props) {
  const [status, setStatus] = useState(engineStatus())
  useEffect(() => onEngineStatus(setStatus), [])
  const ready = status === 'ready'

  return (
    <div className="run-bar">
      {daily ? (
        <span className="run-bar__daily">{daily.label}</span>
      ) : (
      <label className="run-bar__scenario">
        Scenario
        <select value={scenario} onChange={(e) => onScenarioChange(e.target.value)}>
          {scenarioOptions.map((option) => (
            <option key={option.label} value={option.label}>
              {option.label}
            </option>
          ))}
        </select>
      </label>
      )}
      <button type="button" className="run-bar__brief" onClick={onBrief}>
        Brief
      </button>
      <button type="button" onClick={onRun} disabled={!ready || running || !canRun || Boolean(daily?.played)}>
        {running ? 'Running…' : daily ? (daily.played ? 'Played today' : 'Submit ▶ (1 try)') : 'Run ▶'}
      </button>
      {!ready && <span className="run-bar__status">{status}</span>}
    </div>
  )
}
