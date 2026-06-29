import { useEffect, useRef, useState } from 'react'
import { useReducedMotion } from '../../hooks/useReducedMotion'

function useStreamedText(text: string, active = true) {
  const rm = useReducedMotion()
  const [shown, setShown] = useState(active ? 0 : text.length)
  const lastText = useRef(text)

  useEffect(() => {
    if (text !== lastText.current) {
      lastText.current = text
      setShown(active ? 0 : text.length)
    }
  }, [text, active])

  useEffect(() => {
    if (rm || !active) { setShown(text.length); return }
    if (shown >= text.length) return
    const id = setTimeout(() => {
      setShown(n => Math.min(text.length, n + Math.max(1, Math.floor(text.length / 160))))
    }, 12)
    return () => clearTimeout(id)
  }, [shown, text, active, rm])

  return { done: shown >= text.length, slice: text.slice(0, shown) }
}

interface StreamedTextProps {
  text: string
  active?: boolean
}

export function StreamedText({ text, active = true }: StreamedTextProps) {
  const { slice, done } = useStreamedText(text, active)
  return (
    <span>
      {slice}
      {!done && (
        <span className="inline-block w-[2px] h-[1em] align-[-2px] ml-[1px] bg-(--accent) animate-pulse" />
      )}
    </span>
  )
}
