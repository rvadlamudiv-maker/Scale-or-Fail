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
}

export function RunBar({ scenario, onScenarioChange, onRun, running, canRun }: Props) {
  const [status, setStatus] = useState(engineStatus())
  useEffect(() => onEngineStatus(setStatus), [])
  const ready = status === 'ready'

  return (
    <div className="run-bar">
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
      <button type="button" onClick={onRun} disabled={!ready || running || !canRun}>
        {running ? 'Running…' : 'Run ▶'}
      </button>
      {!ready && <span className="run-bar__status">{status}</span>}
    </div>
  )
}
