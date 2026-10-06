// Replays a finished run on the canvas, one engine tick at a time.
import { useEffect, useRef, useState } from 'react'

export const SPEEDS = [1, 4, 10] as const

export function useReplay(tickCount: number, secondsPerTick: number, runId: number) {
  const [index, setIndex] = useState(0)
  const [playing, setPlaying] = useState(true)
  const [speed, setSpeed] = useState<number>(4)
  const position = useRef(0) // fractional tick, so slow speeds still move smoothly

  // A new run starts from the beginning.
  useEffect(() => {
    position.current = 0
    setIndex(0)
    setPlaying(true)
  }, [runId])

  useEffect(() => {
    if (!playing || tickCount === 0) return
    let frame = 0
    let last = performance.now()
    const step = (now: number) => {
      const elapsedSeconds = (now - last) / 1000
      last = now
      position.current = Math.min(tickCount - 1, position.current + (elapsedSeconds * speed) / secondsPerTick)
      setIndex(Math.floor(position.current))
      if (position.current >= tickCount - 1) {
        setPlaying(false)
        return
      }
      frame = requestAnimationFrame(step)
    }
    frame = requestAnimationFrame(step)
    return () => cancelAnimationFrame(frame)
  }, [playing, speed, tickCount, secondsPerTick])

  const skipToEnd = () => {
    position.current = tickCount - 1
    setIndex(tickCount - 1)
    setPlaying(false)
  }

  return { index, playing, setPlaying, speed, setSpeed, skipToEnd, done: index >= tickCount - 1 }
}
