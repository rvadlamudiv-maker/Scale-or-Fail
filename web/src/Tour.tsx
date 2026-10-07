// A 5-step first-visit walkthrough. Each step highlights one part of the screen and explains it.
import { useEffect, useLayoutEffect, useRef, useState } from 'react'

type Step = { target: string; place: 'right' | 'left' | 'below'; title: string; body: string }

const STEPS: Step[] = [
  {
    target: '.palette',
    place: 'right',
    title: '1. Build',
    body: 'Drag components onto the canvas. Each one costs money per hour, and the score punishes overspending.',
  },
  {
    target: '.editor__canvas',
    place: 'below',
    title: '2. Wire',
    body: 'Drag from a box’s right dot to another box to send traffic there. Select a box or wire and press Backspace to delete it.',
  },
  {
    target: '.settings',
    place: 'left',
    title: '3. Tune',
    body: 'Click a box or a wire to change it: instances, autoscaling, timeouts, retries, backoff, failover.',
  },
  {
    target: '.run-bar',
    place: 'below',
    title: '4. Survive',
    body: 'Pick a scenario and press Run. Watch the replay: boxes catch fire when overloaded, red dots are failing requests. Incidents recreate real outages from public postmortems.',
  },
  {
    target: '.app__daily',
    place: 'below',
    title: '5. Daily Outage',
    body: 'One incident a day, the same for everyone, one try. Share your grade without giving away your design.',
  },
]

const DONE_KEY = 'scale-or-fail:tutorial-done'

export function tutorialSeen(): boolean {
  try {
    return localStorage.getItem(DONE_KEY) === '1'
  } catch {
    return true // storage unavailable: don't nag on every visit
  }
}

const CARD_WIDTH = 320
const GAP = 14

export function Tour({ onClose }: { onClose: () => void }) {
  const [step, setStep] = useState(0)
  const [rect, setRect] = useState<DOMRect | null>(null)
  const nextButton = useRef<HTMLButtonElement>(null)
  const current = STEPS[step]
  const last = step === STEPS.length - 1

  const finish = () => {
    try {
      localStorage.setItem(DONE_KEY, '1')
    } catch {
      // ignore
    }
    onClose()
  }

  // Find the highlighted element, and follow it if the window resizes.
  useLayoutEffect(() => {
    const measure = () => setRect(document.querySelector(current.target)?.getBoundingClientRect() ?? null)
    measure()
    window.addEventListener('resize', measure)
    return () => window.removeEventListener('resize', measure)
  }, [current.target])

  useEffect(() => {
    nextButton.current?.focus()
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && finish()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  // Put the card beside or below the highlighted element, kept on screen.
  let top = window.innerHeight / 2 - 100
  let left = window.innerWidth / 2 - CARD_WIDTH / 2
  if (rect) {
    if (current.place === 'right') [top, left] = [rect.top + 24, rect.right + GAP]
    if (current.place === 'left') [top, left] = [rect.top + 24, rect.left - CARD_WIDTH - GAP]
    if (current.place === 'below') [top, left] = [rect.bottom + GAP, rect.left]
  }
  left = Math.max(12, Math.min(left, window.innerWidth - CARD_WIDTH - 12))
  top = Math.max(12, Math.min(top, window.innerHeight - 220))

  return (
    <div className="tour" role="dialog" aria-modal="true" aria-labelledby="tour-title">
      {rect && (
        <div
          className="tour__spotlight"
          style={{ top: rect.top - 4, left: rect.left - 4, width: rect.width + 8, height: rect.height + 8 }}
        />
      )}
      <div className="tour__card" style={{ top, left, width: CARD_WIDTH }}>
        <h2 id="tour-title">{current.title}</h2>
        <p>{current.body}</p>
        <div className="tour__actions">
          <span className="tour__count">
            {step + 1} / {STEPS.length}
          </span>
          <button type="button" className="tour__skip" onClick={finish}>
            Skip
          </button>
          {step > 0 && (
            <button type="button" className="tour__back" onClick={() => setStep(step - 1)}>
              Back
            </button>
          )}
          <button type="button" ref={nextButton} onClick={() => (last ? finish() : setStep(step + 1))}>
            {last ? 'Start playing' : 'Next'}
          </button>
        </div>
      </div>
    </div>
  )
}
