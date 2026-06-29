import { RefreshCw, ShieldCheck } from 'lucide-react'
import { Button } from '../components/ui/Button'
import { StepCounter } from '../components/ui/StepCounter'
import type { HardwareInfo, ManagedPlan } from '../lib/api'

interface HardwareStepProps {
  hardware: HardwareInfo | null
  done: boolean
  plan: ManagedPlan | null
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
      <span className="font-medium text-(--ink)">{revealed ? value : '…'}</span>
    </div>
  )
}

function PlanPreview({ plan }: { plan: ManagedPlan }) {
  if (!plan) return null
  const isReject = plan.path === 'reject'
  const iconMap: Record<string, string> = {
    gpu: 'GPU',
    apple: 'Apple',
    cpu_only: 'CPU',
    reject: 'BYO',
  }
  const icon = iconMap[plan.path] || '—'

  return (
    <div className="mt-4 p-3 rounded-lg border border-(--border) bg-(--surface-2)">
      <div className="flex items-center justify-between text-[12px]">
        <span className="text-(--ink-muted)">Detected plan</span>
        <span className="font-medium text-(--ink) flex items-center gap-1">
          <ShieldCheck className="w-3.5 h-3.5 text-(--accent)" />
          {plan.plan_id || icon}
        </span>
      </div>
      {!isReject && plan.orchestrator && (
        <div className="mt-1 text-[12px] text-(--ink-muted)">
          {plan.orchestrator.model} {plan.orchestrator.quant} · {plan.helper_count} helpers
        </div>
      )}
      {isReject && (
        <div className="mt-1 text-[12px] text-red-600 dark:text-red-400">
          Does not qualify for managed local setup
        </div>
      )}
    </div>
  )
}

export function HardwareStep({ hardware, done, plan, onNext, onBack }: HardwareStepProps) {
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

      {done && plan && (
        <PlanPreview plan={plan} />
      )}

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
