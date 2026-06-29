import { Button } from '../components/ui/Button'
import { StepCounter } from '../components/ui/StepCounter'
import type { CatalogModel } from '../lib/api'

interface DownloadStepProps {
  models: CatalogModel[]
  progress: Record<string, number>
  done: boolean
  onFinish: () => void
  onBack: () => void
}

export function DownloadStep({ models, progress, done, onFinish, onBack }: DownloadStepProps) {
  const selected = models.filter(m => m.fit === 'ok')

  return (
    <div>
      <StepCounter current={3} total={3} />
      <h2 className="mt-3 text-[22px] font-semibold tracking-tight text-(--ink)">
        {done ? "You're ready" : 'Downloading models'}
      </h2>
      <p className="mt-2 text-[14px] text-(--ink-muted) leading-relaxed">
        {done
          ? 'All models are on your machine. Everything runs locally from here.'
          : 'This runs in the background. The downloads will finish while you work.'}
      </p>

      <div className="mt-8 space-y-4">
        {selected.map(m => {
          const pct = Math.round(progress[m.id] ?? 0)
          return (
            <div key={m.id}>
              <div className="flex items-center justify-between text-[13px] mb-1.5">
                <span className="font-medium text-(--ink)">{m.name}</span>
                <span className="text-(--ink-muted) tabular-nums">{pct}% · {m.size}</span>
              </div>
              <div className="h-1.5 rounded-full bg-(--surface-2) overflow-hidden">
                <div
                  className="h-full bg-(--accent) transition-[width] duration-200"
                  style={{ width: `${pct}%` }}
                />
              </div>
            </div>
          )
        })}
      </div>

      <div className="mt-8 flex items-center justify-between">
        <Button variant="ghost" onClick={onBack} disabled={!done}>Back</Button>
        <Button onClick={onFinish} disabled={!done}>Open workspace</Button>
      </div>
    </div>
  )
}
