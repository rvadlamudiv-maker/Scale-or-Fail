// Today's Daily Outage result: spoiler-free (no design details), with copy and image download.
import { useState } from 'react'
import { shareText, type DailyRecord } from './daily'

const SQUARE_COLOR: Record<string, string> = { '🟦': '#4cc2ff', '🟨': '#f5b841', '🟥': '#ff5a36' }

function drawImage(r: DailyRecord): string {
  // A 1200x630 card: the size LinkedIn shows link and image previews at.
  const canvas = document.createElement('canvas')
  canvas.width = 1200
  canvas.height = 630
  const ctx = canvas.getContext('2d')!
  ctx.fillStyle = '#0b0f14'
  ctx.fillRect(0, 0, 1200, 630)
  ctx.fillStyle = '#8b98a5'
  ctx.font = '600 32px "JetBrains Mono", monospace'
  ctx.fillText(`SCALE OR FAIL · DAILY OUTAGE #${r.number}`, 80, 110)
  ctx.fillStyle = '#e6edf3'
  ctx.font = '700 64px "Space Grotesk", sans-serif'
  ctx.fillText(r.title, 80, 200)
  ctx.font = '700 150px "Space Grotesk", sans-serif'
  ctx.fillStyle = ['S', 'A'].includes(r.grade) ? '#4cc2ff' : ['B', 'C'].includes(r.grade) ? '#f5b841' : '#ff5a36'
  ctx.fillText(r.grade, 80, 380)
  ctx.fillStyle = '#e6edf3'
  ctx.font = '600 44px "JetBrains Mono", monospace'
  ctx.fillText(`${r.total.toLocaleString()} pts`, 260, 330)
  ctx.fillStyle = '#8b98a5'
  ctx.font = '400 30px "JetBrains Mono", monospace'
  ctx.fillText(
    `${(r.availability * 100).toFixed(2)}% up · p99 ${Math.round(r.p99_ms).toLocaleString()} ms · $${Math.round(r.cost_per_hour).toLocaleString()}/hr`,
    80,
    450,
  )
  Array.from(r.strip).forEach((square, i) => {
    ctx.fillStyle = SQUARE_COLOR[square] ?? '#2a3644'
    ctx.beginPath()
    ctx.roundRect(80 + i * 72, 500, 60, 60, 10)
    ctx.fill()
  })
  return canvas.toDataURL('image/png')
}

export function ShareCard({ record, nextNumber, onClose }: { record: DailyRecord; nextNumber: number; onClose: () => void }) {
  const [copied, setCopied] = useState(false)
  const url = window.location.origin

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(shareText(record, url))
      setCopied(true)
      window.setTimeout(() => setCopied(false), 2000)
    } catch {
      setCopied(false)
    }
  }

  const download = () => {
    const link = document.createElement('a')
    link.href = drawImage(record)
    link.download = `scale-or-fail-daily-${record.number}.png`
    link.click()
  }

  return (
    <section className="share" aria-label="Your Daily Outage result">
      <p className="share__eyebrow">Daily Outage #{record.number}</p>
      <h2 className="share__title">{record.title}</h2>
      <p className="share__grade">
        Grade <b>{record.grade}</b> · {record.total.toLocaleString()} pts
      </p>
      <p className="share__strip" aria-label="How users fared over the run">
        {record.strip}
      </p>
      <pre className="share__text">{shareText(record, url)}</pre>
      <div className="share__actions">
        <button type="button" onClick={copy}>
          {copied ? 'Copied!' : 'Copy result'}
        </button>
        <button type="button" onClick={download}>
          Download image
        </button>
        <button type="button" className="share__close" onClick={onClose}>
          Close
        </button>
      </div>
      <p className="share__next">One attempt per day. Come back tomorrow for Daily Outage #{nextNumber}.</p>
    </section>
  )
}
