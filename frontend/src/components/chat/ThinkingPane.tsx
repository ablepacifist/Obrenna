import { useState } from 'react'

interface ThinkingPaneProps {
  text: string
  expanded: boolean
  onExpandedChange: (expanded: boolean) => void
  /** Live means the model is still reasoning: pulse the dot, use present tense.
   *  False is a finished trace replayed from the transcript. */
  live?: boolean
}

/**
 * Collapsible pane showing the model's reasoning trace.
 *
 * Used twice: streaming, for the in-flight message (ChatThread auto-collapses
 * it once answer tokens begin), and afterwards via ThinkingBlock for the
 * persisted `thinking` block. Reasoning used to be discarded at `done`, so the
 * answer to "what were you thinking?" disappeared the moment it mattered.
 */
export function ThinkingPane({ text, expanded, onExpandedChange, live = true }: ThinkingPaneProps) {
  if (!text.trim()) return null

  return (
    <div className="mb-3 rounded-lg border border-(--border) bg-(--surface-2) text-[13px]">
      <button
        type="button"
        onClick={() => onExpandedChange(!expanded)}
        className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-(--ink-muted) transition-colors hover:text-(--ink)"
        aria-expanded={expanded}
      >
        <span className="inline-flex items-center gap-1.5">
          <span className={`w-1.5 h-1.5 rounded-full bg-(--accent) ${live ? 'animate-pulse' : ''}`} />
          {live ? 'Thinking' : 'Thought process'}
        </span>
        <span className="text-[11px] text-(--ink-faint)">{expanded ? 'Hide' : 'Show'}</span>
      </button>
      {expanded && (
        <div className="whitespace-pre-wrap border-t border-(--border) px-3 py-2 text-(--ink-muted) leading-relaxed">
          {text}
        </div>
      )}
    </div>
  )
}

/** A persisted reasoning block in a replayed transcript. Collapsed by default —
 *  it is reference material, not the answer. */
export function ThinkingBlock({ text }: { text: string }) {
  const [expanded, setExpanded] = useState(false)
  return <ThinkingPane text={text} expanded={expanded} onExpandedChange={setExpanded} live={false} />
}
