// The Daily Outage leaderboard API (a Cloudflare Pages Function backed by D1).
//   GET  /api/daily/9  -> how many played Daily Outage #9, and the top 20
//   POST /api/daily/9  -> submit your result (one attempt per player per day)
// Scores sent by the browser are claims. A nightly job re-runs each design with the
// deterministic engine and marks matching scores verified (or hides the rest).

const DAY_ONE = Date.UTC(2026, 9, 1) // Daily Outage #1: October 1, 2026
const GRADES = ['S', 'A', 'B', 'C', 'D', 'F']
const MAX_DESIGN_BYTES = 20_000

const json = (body, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })

function dailyNumberNow() {
  return Math.floor((Date.now() - DAY_ONE) / 86_400_000) + 1
}

function readNumber(params) {
  const n = Number(params.number)
  return Number.isInteger(n) && n >= 1 ? n : null
}

export async function onRequestGet({ params, env }) {
  const daily = readNumber(params)
  if (!daily) return json({ error: 'Unknown Daily Outage.' }, 400)
  const { results } = await env.DB.prepare(
    `SELECT name, grade, total, availability, p99_ms, cost_per_hour, verified
       FROM daily_results
      WHERE daily = ? AND hidden = 0
      ORDER BY total DESC, cost_per_hour ASC, created_at ASC
      LIMIT 20`,
  )
    .bind(daily)
    .all()
  const { players } = await env.DB.prepare(
    'SELECT COUNT(*) AS players FROM daily_results WHERE daily = ? AND hidden = 0',
  )
    .bind(daily)
    .first()
  return json({ daily, players, top: results })
}

export async function onRequestPost({ params, request, env }) {
  const daily = readNumber(params)
  // Players are in different time zones, so accept yesterday's and tomorrow's daily too.
  if (!daily || Math.abs(daily - dailyNumberNow()) > 1) {
    return json({ error: 'That Daily Outage is closed.' }, 400)
  }

  let body
  try {
    body = await request.json()
  } catch {
    return json({ error: 'Send JSON.' }, 400)
  }
  const { player_id, name, grade, total, availability, p99_ms, cost_per_hour, design_yaml } = body ?? {}
  const cleanName = String(name ?? '').trim().replace(/\s+/g, ' ').slice(0, 24)
  const problems = [
    typeof player_id === 'string' && /^[a-z0-9-]{8,64}$/.test(player_id) ? null : 'player_id',
    cleanName.length >= 2 ? null : 'name (2-24 characters)',
    GRADES.includes(grade) ? null : 'grade',
    Number.isInteger(total) && total >= 0 && total <= 11_000 ? null : 'total',
    typeof availability === 'number' && availability >= 0 && availability <= 1 ? null : 'availability',
    typeof p99_ms === 'number' && p99_ms >= 0 ? null : 'p99_ms',
    typeof cost_per_hour === 'number' && cost_per_hour >= 0 ? null : 'cost_per_hour',
    typeof design_yaml === 'string' && design_yaml.length > 0 && design_yaml.length <= MAX_DESIGN_BYTES
      ? null
      : 'design_yaml',
  ].filter(Boolean)
  if (problems.length) return json({ error: `Check these fields: ${problems.join(', ')}.` }, 400)

  const result = await env.DB.prepare(
    `INSERT OR IGNORE INTO daily_results
       (daily, player_id, name, grade, total, availability, p99_ms, cost_per_hour, design_yaml)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
  )
    .bind(daily, player_id, cleanName, grade, total, availability, p99_ms, cost_per_hour, design_yaml)
    .run()
  if (result.meta.changes === 0) return json({ error: 'You already submitted today.' }, 409)

  const { rank } = await env.DB.prepare(
    'SELECT COUNT(*) + 1 AS rank FROM daily_results WHERE daily = ? AND hidden = 0 AND total > ?',
  )
    .bind(daily, total)
    .first()
  return json({ ok: true, rank })
}
