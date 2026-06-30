import { Button } from '../components/ui/Button'
import { StepCounter } from '../components/ui/StepCounter'
import type { CatalogModel } from '../lib/api'

interface DownloadStepProps {
  models: CatalogModel[]
  progress: Record<string, number>
  status: Record<string, string>
  error: string | null
  done: boolean
  onRetry: () => void
  onFinish: () => void
  onBack: () => void
}

export function DownloadStep({ models, progress, status, error, done, onRetry, onFinish, onBack }: DownloadStepProps) {
  const selected = models.filter(m => m.fit === 'ok')

  const labelForStatus = (s: string) => {
    if (s === 'ready') return 'Ready'
    if (s === 'failed') return 'Failed'
    if (s === 'verifying') return 'Verifying'
    if (s === 'downloading') return 'Downloading'
    if (s === 'checking') return 'Checking'
    return 'Queued'
  }

  return (
    <div>
      <StepCounter current={3} total={3} />
      <h2 className="mt-3 text-[22px] font-semibold tracking-tight text-(--ink)">
        {done ? 'You\'re ready' : 'Preparing your setup'}
      </h2>
      <p className="mt-2 text-[14px] text-(--ink-muted) leading-relaxed">
        {done
          ? 'All models are on your machine. Everything runs locally from here.'
          : 'This runs in the background. Preparing models for your detected hardware.'}
      </p>

      <div className="mt-8 space-y-4">
        {selected.map(m => {
          const pct = Math.round(progress[m.id] ?? 0)
          const st = status[m.id] ?? 'queued'
          return (
            <div key={m.id}>
              <div className="flex items-center justify-between text-[13px] mb-1.5">
                <span className="font-medium text-(--ink)">{m.name}</span>
                <span className="text-(--ink-muted) tabular-nums">{labelForStatus(st)} · {pct}% · {m.size}</span>
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
        {selected.length === 0 && (
          <div className="p-4 text-[13px] text-(--ink-muted) rounded-xl border border-(--border) bg-(--surface-2)">
            No models to download for this configuration.
          </div>
        )}
        {error && (
          <div className="p-4 text-[13px] text-(--err) rounded-xl border border-(--err)/25 bg-(--err)/5">
            {error}
          </div>
        )}
      </div>

      <div className="mt-8 flex items-center justify-between">
        <Button variant="ghost" onClick={onBack} disabled={!done}>Back</Button>
        <div className="flex items-center gap-2">
          {error && !done && <Button variant="ghost" onClick={onRetry}>Retry failed</Button>}
          <Button onClick={onFinish} disabled={!done}>Open workspace</Button>
        </div>
      </div>
    </div>
  )
}
