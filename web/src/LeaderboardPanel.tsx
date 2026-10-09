// Today's Daily Outage leaderboard: the top 20, best score first (ties go to the cheaper design).
import { useEffect, useState } from 'react'
import { fetchLeaderboard, type Leaderboard } from './leaderboard'

type Props = { daily: number; title: string; onClose: () => void }

export function LeaderboardPanel({ daily, title, onClose }: Props) {
  const [board, setBoard] = useState<Leaderboard | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchLeaderboard(daily)
      .then(setBoard)
      .catch((e: Error) => setError(e.message))
  }, [daily])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="board" role="dialog" aria-modal="true" aria-labelledby="board-title" onClick={onClose}>
      <section className="board__card" onClick={(e) => e.stopPropagation()}>
        <p className="board__eyebrow">Daily Outage #{daily}</p>
        <h2 id="board-title" className="board__title">
          {title}
        </h2>
        {error && <p className="board__note">{error}</p>}
        {!board && !error && <p className="board__note">Loading the leaderboard…</p>}
        {board && board.top.length === 0 && (
          <p className="board__note">Nobody has submitted yet. Play today’s Daily Outage and take #1.</p>
        )}
        {board && board.top.length > 0 && (
          <>
            <p className="board__note">
              {board.players.toLocaleString()} {board.players === 1 ? 'player' : 'players'} so far
            </p>
            <ol className="board__list">
              {board.top.map((row, i) => (
                <li key={`${i}-${row.name}`}>
                  <span className="board__rank">#{i + 1}</span>
                  <span className="board__name">{row.name}</span>
                  <span className={`board__grade board__grade--${row.grade}`}>{row.grade}</span>
                  <span className="board__num">{row.total.toLocaleString()}</span>
                  <span className="board__num">${Math.round(row.cost_per_hour).toLocaleString()}/hr</span>
                  <span className="board__verified" title={row.verified ? 'Verified: the design was re-run and the score matched' : 'Checked overnight'}>
                    {row.verified ? '✓' : '…'}
                  </span>
                </li>
              ))}
            </ol>
          </>
        )}
        <p className="board__legend">
          ✓ verified: the design was re-run on the engine and the score matched. Scores marked … are checked overnight.
        </p>
        <button type="button" className="board__close" onClick={onClose}>
          Close
        </button>
      </section>
    </div>
  )
}
