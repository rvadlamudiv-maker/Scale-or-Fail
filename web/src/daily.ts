// The Daily Outage: one incident a day, the same for everyone, one attempt, a shareable result.
import { parse } from 'yaml'
import { scenarioOptions } from './design'
import rotationJson from '../../incidents/rotation.json?raw'
import type { RunResult } from './engine/client'

const DAY_ONE = '2026-10-01' // Daily Outage #1

export function todayKey(date = new Date()): string {
  // The player's local calendar day, e.g. "2026-10-07".
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

export function dailyNumber(key = todayKey()): number {
  const [y, m, d] = key.split('-').map(Number)
  const [y1, m1, d1] = DAY_ONE.split('-').map(Number)
  return Math.round((Date.UTC(y, m - 1, d) - Date.UTC(y1, m1 - 1, d1)) / 86_400_000) + 1
}

export type Daily = {
  number: number
  key: string
  incident: string // folder name, e.g. "retry_storm"
  title: string // scenario name, e.g. "The Retry Storm"
  scenarioYaml: string
}

// Which incident each daily plays (shared with the nightly verifier). New incidents start a new
// era at a future daily number, so past dailies never change.
type Era = { from_daily: number; incidents: string[] }
const ERAS = (JSON.parse(rotationJson) as { eras: Era[] }).eras

export function incidentFor(number: number): string {
  const era = ERAS.filter((e) => e.from_daily <= number).at(-1)!
  return era.incidents[(number - era.from_daily) % era.incidents.length]
}

export function todaysDaily(): Daily {
  const key = todayKey()
  const number = Math.max(1, dailyNumber(key))
  const option = scenarioOptions.find((s) => s.label === `Incident: ${incidentFor(number)}`)!
  // Same traffic for everyone today, different traffic tomorrow: the day number is the seed.
  // Only the seed line changes. (Re-writing the whole YAML can drop quotes, e.g. around dates.)
  const seedLine = /^seed:.*$/m
  const scenarioYaml = seedLine.test(option.yaml)
    ? option.yaml.replace(seedLine, `seed: ${number}`)
    : `${option.yaml}\nseed: ${number}\n`
  return {
    number,
    key,
    incident: option.label.replace('Incident: ', ''),
    title: (parse(option.yaml) as { name: string }).name,
    scenarioYaml,
  }
}

export type DailyRecord = {
  number: number
  title: string
  grade: string
  total: number
  availability: number
  p99_ms: number
  cost_per_hour: number
  strip: string // 10 squares, one per tenth of the run: how users fared, without giving the design away
  design_yaml?: string // the design behind the result, sent to the leaderboard so the score can be re-run
}

export function recordFrom(daily: Daily, result: Extract<RunResult, { ok: true }>, designYaml = ''): DailyRecord {
  const buckets = 10
  const size = Math.ceil(result.ticks.length / buckets)
  let strip = ''
  for (let b = 0; b < buckets; b++) {
    const slice = result.ticks.slice(b * size, (b + 1) * size)
    const ok = slice.reduce((sum, t) => sum + t.ok, 0) / Math.max(1, slice.length)
    strip += ok >= result.goals.availability ? '🟦' : ok >= 0.95 ? '🟨' : '🟥'
  }
  return {
    number: daily.number,
    title: daily.title,
    grade: result.score.grade,
    total: result.score.total,
    availability: result.metrics.availability,
    p99_ms: result.metrics.p99_ms,
    cost_per_hour: result.metrics.cost_per_hour,
    strip,
    design_yaml: designYaml,
  }
}

const storageKey = (key: string) => `scale-or-fail:daily:${key}`

export function loadDaily(key: string): DailyRecord | null {
  try {
    const saved = localStorage.getItem(storageKey(key))
    return saved ? (JSON.parse(saved) as DailyRecord) : null
  } catch {
    return null // private browsing or storage turned off: just don't remember
  }
}

export function saveDaily(key: string, record: DailyRecord) {
  try {
    localStorage.setItem(storageKey(key), JSON.stringify(record))
  } catch {
    // ignore: the result still shows, it just won't be remembered
  }
}

export function shareText(r: DailyRecord, url: string): string {
  return [
    `Scale or Fail #${r.number} · ${r.title}`,
    `Grade ${r.grade} · ${r.total.toLocaleString()} pts`,
    r.strip,
    `${(r.availability * 100).toFixed(2)}% up · p99 ${Math.round(r.p99_ms).toLocaleString()} ms · $${Math.round(r.cost_per_hour).toLocaleString()}/hr`,
    url,
  ].join('\n')
}
