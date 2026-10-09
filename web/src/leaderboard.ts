// Talks to the leaderboard API (web/functions/api/daily/[number].js).
import type { DailyRecord } from './daily'

export type LeaderboardRow = {
  name: string
  grade: string
  total: number
  availability: number
  p99_ms: number
  cost_per_hour: number
  verified: number // 1 once the nightly re-run matched the claimed score
}

export type Leaderboard = { daily: number; players: number; top: LeaderboardRow[] }

// Browser storage can be unavailable (private windows); the leaderboard still works without it.
const read = (key: string) => {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}
const write = (key: string, value: string) => {
  try {
    localStorage.setItem(key, value)
  } catch {
    // ignore
  }
}

// A random id that marks this browser as one player, so each player gets one attempt per day.
export function playerId(): string {
  let id = read('scale-or-fail:player-id')
  if (!id) {
    id = crypto.randomUUID()
    write('scale-or-fail:player-id', id)
  }
  return id
}

export const savedName = () => read('scale-or-fail:name') ?? ''

// The rank this browser got when it submitted (0 = submitted, rank unknown), or null if it hasn't.
export function submittedRank(daily: number): number | null {
  const value = read(`scale-or-fail:submitted:${daily}`)
  return value === null ? null : Number(value)
}

export async function submitScore(
  record: DailyRecord,
  name: string,
): Promise<{ ok: true; rank: number } | { ok: false; error: string }> {
  write('scale-or-fail:name', name)
  try {
    const response = await fetch(`/api/daily/${record.number}`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        player_id: playerId(),
        name,
        grade: record.grade,
        total: record.total,
        availability: record.availability,
        p99_ms: record.p99_ms,
        cost_per_hour: record.cost_per_hour,
        design_yaml: record.design_yaml,
      }),
    })
    const body = await response.json()
    if (response.status === 409) {
      write(`scale-or-fail:submitted:${record.number}`, '0')
      return { ok: true, rank: 0 }
    }
    if (!response.ok) return { ok: false, error: body.error ?? 'Something went wrong. Try again.' }
    write(`scale-or-fail:submitted:${record.number}`, String(body.rank))
    return { ok: true, rank: body.rank }
  } catch {
    return { ok: false, error: 'Couldn’t reach the leaderboard. Try again in a moment.' }
  }
}

export async function fetchLeaderboard(daily: number): Promise<Leaderboard> {
  const response = await fetch(`/api/daily/${daily}`)
  if (!response.ok) throw new Error('Couldn’t load the leaderboard. Try again in a moment.')
  return response.json()
}
