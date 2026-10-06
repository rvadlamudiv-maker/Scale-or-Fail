// The replay HUD: the clock, how users are doing right now, and playback controls.
import { SPEEDS } from './useReplay'

type Props = {
  t: number
  duration: number
  ok: number
  e2eMs: number
  latestEvent: string | null
  playing: boolean
  onPlayPause: () => void
  speed: number
  onSpeed: (speed: number) => void
  onSkip: () => void
}

const clock = (s: number) => `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(Math.floor(s % 60)).padStart(2, '0')}`

export function Playback({ t, duration, ok, e2eMs, latestEvent, playing, onPlayPause, speed, onSpeed, onSkip }: Props) {
  const okClass = ok >= 0.999 ? 'is-good' : ok >= 0.95 ? 'is-warn' : 'is-bad'
  const latencyClass = e2eMs <= 500 ? 'is-good' : e2eMs <= 1000 ? 'is-warn' : 'is-bad'
  return (
    <div className="playback">
      <div className="playback__stats">
        <span className="playback__clock">
          {clock(t)} <span>/ {clock(duration)}</span>
        </span>
        <span>
          requests OK <b className={okClass}>{(ok * 100).toFixed(1)}%</b>
        </span>
        <span>
          end-to-end <b className={latencyClass}>{Math.round(e2eMs).toLocaleString()} ms</b>
        </span>
      </div>
      <div className="playback__controls">
        <button type="button" onClick={onPlayPause}>
          {playing ? 'Pause' : 'Play'}
        </button>
        {SPEEDS.map((s) => (
          <button key={s} type="button" className={s === speed ? 'is-active' : ''} onClick={() => onSpeed(s)}>
            {s}×
          </button>
        ))}
        <button type="button" onClick={onSkip}>
          Skip to results
        </button>
      </div>
      {latestEvent && <div className="playback__event">⚡ {latestEvent}</div>}
    </div>
  )
}
