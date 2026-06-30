import type { ReactNode } from 'react'
import { useTheme } from '../../theme/ThemeProvider'
import DarkHorizontalLogo from '../../assets/logos/ObrennaDarkHorizontal.png'
import LightHorizontalLogo from '../../assets/logos/ObrennaLightHorizontal.png'

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
  const { resolvedTheme } = useTheme()
  const logoSrc = resolvedTheme === 'dark' ? DarkHorizontalLogo : LightHorizontalLogo

  return (
    <div className="flex-1 flex flex-col items-center justify-center px-6">
      <div className="w-full max-w-[640px]">
        <div className="mb-6 flex flex-col items-center gap-5">
          <img
            src={logoSrc}
            alt="Obrenna logo"
            className="h-auto w-auto max-w-[480px] object-contain"
          />
        </div>
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
