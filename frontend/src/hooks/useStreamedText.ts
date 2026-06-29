import { useEffect, useRef, useState } from 'react'
import { useReducedMotion } from './useReducedMotion'

/** Animates text appearing character by character. Pass `text` when ready. */
export function useStreamedText(text: string, speedMs = 12): string {
  const reduced = useReducedMotion()
  const [displayed, setDisplayed] = useState('')
  const ref = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (reduced) {
      setDisplayed(text)
      return
    }
    setDisplayed('')
    let i = 0
    function step() {
      i++
      setDisplayed(text.slice(0, i))
      if (i < text.length) ref.current = setTimeout(step, speedMs)
    }
    ref.current = setTimeout(step, speedMs)
    return () => { if (ref.current) clearTimeout(ref.current) }
  }, [text, reduced, speedMs])

  return displayed
}
