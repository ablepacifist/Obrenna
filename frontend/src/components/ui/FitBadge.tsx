import { AlertTriangle, Ban, Check } from 'lucide-react'

interface FitBadgeProps {
  fit: 'ok' | 'warn' | 'bad'
  note: string
}

export function FitBadge({ fit, note }: FitBadgeProps) {
  if (fit === 'ok')
    return (
      <span className="inline-flex items-center gap-1 text-[12px] text-(--ok)" title={note}>
        <Check className="w-3.5 h-3.5" strokeWidth={2.5} />
        <span className="text-(--ink-muted)">Runs well</span>
      </span>
    )
  if (fit === 'warn')
    return (
      <span className="inline-flex items-center gap-1 text-[12px] text-(--warn)" title={note}>
        <AlertTriangle className="w-3.5 h-3.5" strokeWidth={2.5} />
        <span className="text-(--ink-muted)">Runs slowly</span>
      </span>
    )
  return (
    <span className="inline-flex items-center gap-1 text-[12px] text-(--err)" title={note}>
      <Ban className="w-3.5 h-3.5" strokeWidth={2.5} />
      <span className="text-(--ink-muted)">Too large</span>
    </span>
  )
}
