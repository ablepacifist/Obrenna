import { useEffect, useRef, useState, useMemo } from 'react'
import { useReducedMotion } from '../../hooks/useReducedMotion'
import { useAnimationPreference } from '../../context/AnimationPreferenceContext'

interface StreamedTextProps {
  text: string
  active?: boolean
}

export function StreamedText({ text, active = true }: StreamedTextProps) {
  const rm = useReducedMotion()
  const { style } = useAnimationPreference()
  const lastText = useRef(text)

  const tokens = useMemo(() => text.split(/(\s+)/), [text])

  const wordTokenIndices = useMemo(
    () => tokens.map((t, i) => (t.trim().length > 0 ? i : -1)).filter(i => i >= 0),
    [tokens],
  )

  const fullCount = wordTokenIndices.length

  const [revealedCount, setRevealedCount] = useState(
    text.length === 0 || rm || !active || style === 'none' ? fullCount : 0,
  )

  // Reset when text changes
  useEffect(() => {
    if (text !== lastText.current) {
      lastText.current = text
      setRevealedCount(
        text.length === 0 || rm || !active || style === 'none' ? fullCount : 0,
      )
    }
  }, [text, active, rm, style, fullCount])

  // Reveal one word at a time
  useEffect(() => {
    if (rm || !active || style === 'none' || revealedCount >= fullCount) {
      setRevealedCount(fullCount)
      return
    }
    const id = setTimeout(() => {
      setRevealedCount(n => Math.min(fullCount, n + 1))
    }, 50)
    return () => clearTimeout(id)
  }, [revealedCount, fullCount, active, rm, style])

  const done = revealedCount >= fullCount

  const elements = useMemo(() => {
    const result: React.ReactNode[] = []
    let wordIdx = 0

    for (let i = 0; i < tokens.length; i++) {
      const token = tokens[i]
      if (!token.trim()) {
        result.push(<span key={`s-${i}`}>{token}</span>)
      } else {
        if (wordIdx < revealedCount) {
          const animClass =
            style === 'claude'
              ? 'word-reveal-claude'
              : style === 'clean'
                ? 'word-reveal-clean'
                : ''
          result.push(
            <span key={`w-${wordIdx}`} className={animClass}>
              {token}
            </span>,
          )
        } else {
          result.push(<span key={`h-${i}`} className="invisible">{token}</span>)
        }
        wordIdx++
      }
    }

    return result
  }, [tokens, revealedCount, style])

  const showCursor = active && !done && style !== 'none' && !rm

  if (!text) {
    return <span />
  }

  return (
    <span>
      {elements}
      {showCursor && (
        <span className="inline-block w-[2px] h-[1em] align-[-2px] ml-[1px] bg-(--accent) animate-pulse" />
      )}
    </span>
  )
}
