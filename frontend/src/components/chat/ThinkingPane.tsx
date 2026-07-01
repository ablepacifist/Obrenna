interface ThinkingPaneProps {
  text: string
  expanded: boolean
  onExpandedChange: (expanded: boolean) => void
}

/**
 * Collapsible pane that shows an ephemeral reasoning/thinking trace streaming
 * from the model. Not persisted — only renders for the in-flight assistant
 * message. Auto-collapsed by ChatThread once answer content begins streaming.
 */
export function ThinkingPane({ text, expanded, onExpandedChange }: ThinkingPaneProps) {
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
          <span className="w-1.5 h-1.5 rounded-full bg-(--accent) animate-pulse" />
          Thinking
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