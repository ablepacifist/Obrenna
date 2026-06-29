import { RefreshCw } from 'lucide-react'
import { Button } from '../components/ui/Button'
import { StepCounter } from '../components/ui/StepCounter'
import type { HardwareInfo } from '../lib/api'

interface HardwareStepProps {
  hardware: HardwareInfo | null
  done: boolean
  onNext: () => void
  onBack: () => void
}

function HardwareRow({ label, value, revealed, index }: { label: string; value: string; revealed: boolean; index: number }) {
  return (
    <div
      className="px-4 h-12 flex items-center justify-between text-[13px] transition-opacity duration-300"
      style={{ opacity: revealed ? 1 : 0.4, transitionDelay: `${index * 120}ms` }}
    >
      <span className="text-(--ink-muted)">{label}</span>
      <span className="font-medium text-(--ink)">{revealed ? value : 'Reading…'}</span>
    </div>
  )
}

export function HardwareStep({ hardware, done, onNext, onBack }: HardwareStepProps) {
  const rows = hardware
    ? [
        { key: 'cpu', label: 'Processor', value: hardware.cpu },
        { key: 'ram_gb', label: 'Memory', value: hardware.ram_gb ? `${hardware.ram_gb} GB` : 'Unknown' },
        { key: 'gpu', label: 'Graphics', value: hardware.gpu?.[0]?.name ?? 'Integrated' },
        { key: 'vram_gb', label: 'Graphics memory', value: hardware.vram_gb ? `${hardware.vram_gb} GB` : 'Shared' },
      ]
    : [
        { key: 'cpu', label: 'Processor', value: '…' },
        { key: 'ram_gb', label: 'Memory', value: '…' },
        { key: 'gpu', label: 'Graphics', value: '…' },
        { key: 'vram_gb', label: 'Graphics memory', value: '…' },
      ]

  return (
    <div>
      <StepCounter current={1} total={3} />
      <h2 className="mt-3 text-[22px] font-semibold tracking-tight text-(--ink)">Checking your machine</h2>
      <p className="mt-2 text-[14px] text-(--ink-muted) leading-relaxed">
        We'll read what you've got and pick models that fit. This takes a few seconds and you only do it once.
      </p>

      <div className="mt-8 rounded-xl border border-(--border) bg-(--surface) divide-y divide-(--border)">
        {rows.map((r, i) => (
          <HardwareRow key={r.key} label={r.label} value={r.value} revealed={done} index={i} />
        ))}
      </div>

      {!done && (
        <div className="mt-5 flex items-center gap-2 text-[13px] text-(--ink-muted)">
          <RefreshCw className="w-3.5 h-3.5 animate-spin" /> Scanning…
        </div>
      )}

      <div className="mt-8 flex items-center justify-between">
        <Button variant="ghost" onClick={onBack}>Back</Button>
        <Button onClick={onNext} disabled={!done}>Continue</Button>
      </div>
    </div>
  )
}
