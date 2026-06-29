import type { ReactNode } from 'react'

const CHIPS = [
  { label: 'Summarize these files', prompt: 'Summarize these files' },
  { label: 'Turn a CSV into a dashboard', prompt: 'Turn a CSV into a dashboard' },
  { label: 'Draft a report', prompt: 'Draft a report' },
]

interface EmptyStateProps {
  onChip: (prompt: string) => void
  composer: ReactNode
}

export function EmptyState({ onChip, composer }: EmptyStateProps) {
  return (
    <div className="flex-1 flex flex-col items-center justify-center px-6">
      <div className="w-full max-w-[640px]">
        <h1 className="text-[22px] font-semibold tracking-tight text-(--ink)">What are we working on?</h1>
        <p className="mt-1.5 text-[14px] text-(--ink-muted) leading-relaxed">
          Drop a file or describe the task. Everything runs on your machine.
        </p>
        <div className="mt-6">{composer}</div>
        <div className="mt-4 flex flex-wrap gap-2">
          {CHIPS.map(c => (
            <button
              key={c.label}
              onClick={() => onChip(c.prompt)}
              className="h-8 px-3 rounded-full border border-(--border) bg-(--surface) text-[12px] text-(--ink) hover:border-(--accent) hover:text-(--accent) focus:outline-none focus-visible:ring-2 focus-visible:ring-(--accent) transition-colors"
            >
              {c.label}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
