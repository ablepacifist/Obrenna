import { useEffect, useRef, useState } from 'react'
import { useReducedMotion } from '../../hooks/useReducedMotion'

interface StreamingScrambleTextProps {
  text: string
  active?: boolean
  durationMs?: number
  className?: string
}

const SCRAMBLE_CHARS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'

function randomChar() {
  return SCRAMBLE_CHARS[Math.floor(Math.random() * SCRAMBLE_CHARS.length)]
}

function isWhitespace(char: string) {
  return /\s/.test(char)
}

// Presentation-only effect: the canonical text remains unchanged and this
// component only changes how newly streamed characters are displayed.
export function StreamingScrambleText({
  text,
  active = true,
  durationMs = 220,
  className,
}: StreamingScrambleTextProps) {
  const reducedMotion = useReducedMotion()
  const [displayText, setDisplayText] = useState(text)
  const previousTextRef = useRef(text)
  const frameRef = useRef<number | null>(null)

  useEffect(() => {
    if (frameRef.current !== null) {
      cancelAnimationFrame(frameRef.current)
      frameRef.current = null
    }

    if (!active || reducedMotion) {
      previousTextRef.current = text
      setDisplayText(text)
      return
    }

    const previousText = previousTextRef.current

    if (!text.startsWith(previousText)) {
      previousTextRef.current = text
      setDisplayText(text)
      return
    }

    const suffix = text.slice(previousText.length)
    if (!suffix) {
      setDisplayText(text)
      return
    }

    const revealableCount = Array.from(suffix).filter(ch => !isWhitespace(ch)).length
    const start = performance.now()

    const tick = (now: number) => {
      const progress = Math.min(1, (now - start) / durationMs)
      const resolvedCount = Math.floor(progress * revealableCount)
      let resolvedSoFar = 0
      let next = previousText

      for (const char of suffix) {
        if (isWhitespace(char)) {
          next += char
        } else if (resolvedSoFar < resolvedCount) {
          next += char
          resolvedSoFar += 1
        } else {
          next += randomChar()
        }
      }

      setDisplayText(next)

      if (progress < 1) {
        frameRef.current = requestAnimationFrame(tick)
      } else {
        previousTextRef.current = text
        setDisplayText(text)
        frameRef.current = null
      }
    }

    frameRef.current = requestAnimationFrame(tick)

    return () => {
      if (frameRef.current !== null) {
        cancelAnimationFrame(frameRef.current)
      }
      frameRef.current = null
    }
  }, [text, active, durationMs, reducedMotion])

  return <span className={className}>{displayText}</span>
}
