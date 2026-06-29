import { Button } from '../components/ui/Button'
import { FitBadge } from '../components/ui/FitBadge'
import { StepCounter } from '../components/ui/StepCounter'
import type { CatalogModel } from '../lib/api'

interface RecommendStepProps {
  catalog: CatalogModel[]
  onNext: () => void
  onBack: () => void
}

export function RecommendStep({ catalog, onNext, onBack }: RecommendStepProps) {
  const selected = catalog.filter(m => m.fit === 'ok')
  const skipped = catalog.filter(m => m.fit !== 'ok')

  return (
    <div>
      <StepCounter current={2} total={3} />
      <h2 className="mt-3 text-[22px] font-semibold tracking-tight text-(--ink)">Recommended setup</h2>
      <p className="mt-2 text-[14px] text-(--ink-muted) leading-relaxed">
        These models fit your machine. We'll use the bigger one when reasoning matters, and the smaller ones for summaries and quick tasks.
      </p>

      <div className="mt-8 rounded-xl border border-(--border) bg-(--surface) divide-y divide-(--border)">
        {selected.map(m => (
          <div key={m.id} className="p-4 flex items-center justify-between gap-4">
            <div className="min-w-0">
              <div className="text-[14px] font-medium text-(--ink)">{m.name}</div>
              <div className="mt-0.5 text-[12px] text-(--ink-muted)">{m.role} · {m.size}</div>
            </div>
            <FitBadge fit={m.fit} note={m.note} />
          </div>
        ))}
        {selected.length === 0 && (
          <div className="p-4 text-[13px] text-(--ink-muted)">No models fit this machine's memory. Use the BYO path to connect an external server.</div>
        )}
      </div>

      {skipped.length > 0 && (
        <div className="mt-6 p-4 rounded-xl border border-(--border) bg-(--surface-2)">
          <div className="text-[13px] text-(--ink) leading-relaxed">
            {skipped.length === 1 ? 'One model' : `${skipped.length} models`} didn't make the cut —{' '}
            {skipped.map(m => m.name).join(', ')}. You can change the selection any time in settings.
          </div>
        </div>
      )}

      <div className="mt-8 flex items-center justify-between">
        <Button variant="ghost" onClick={onBack}>Back</Button>
        <Button onClick={onNext} disabled={selected.length === 0}>Download models</Button>
      </div>
    </div>
  )
}
