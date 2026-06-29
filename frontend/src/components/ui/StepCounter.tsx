import { cn } from '../../lib/cn'

interface StepCounterProps {
  current: number
  total: number
}

export function StepCounter({ current, total }: StepCounterProps) {
  return (
    <div className="flex items-center gap-1.5">
      {Array.from({ length: total }).map((_, i) => (
        <div
          key={i}
          className={cn(
            'h-1 rounded-full transition-all',
            i < current ? 'w-6 bg-(--accent)' : 'w-2 bg-(--border-strong)',
          )}
        />
      ))}
    </div>
  )
}
