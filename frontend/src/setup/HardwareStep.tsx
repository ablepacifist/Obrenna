import { AlertCircle, RefreshCw, ShieldCheck } from 'lucide-react'
import { Button } from '../components/ui/Button'
import { StepCounter } from '../components/ui/StepCounter'
import type { HardwareInfo, ManagedPlan } from '../lib/api'

interface HardwareStepProps {
  hardware: HardwareInfo | null
  done: boolean
  plan: ManagedPlan | null
  hardwareError: boolean
  planError: boolean
  onRetry: () => void
  onNext: () => void
  onBack: () => void
}

function HardwareRow({ label, value, hasData, index }: { label: string; value: string; hasData: boolean; index: number }) {
  return (
    <div
      className="px-4 h-12 flex items-center justify-between text-[13px] transition-opacity duration-300"
      style={{ opacity: hasData ? 1 : 0.4, transitionDelay: `${index * 120}ms` }}
    >
      <span className="text-(--ink-muted)">{label}</span>
      <span className="font-medium text-(--ink)">{hasData ? value : '…'}</span>
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

export function HardwareStep({ hardware, done, plan, hardwareError, planError, onRetry, onNext, onBack }: HardwareStepProps) {
  const rows = [
    { key: 'cpu', label: 'Processor', value: hardware?.cpu ?? '…' },
    { key: 'ram_gb', label: 'Memory', value: hardware ? (hardware.ram_gb ? `${hardware.ram_gb} GB` : 'Unknown') : '…' },
    { key: 'gpu', label: 'Graphics', value: hardware ? (hardware.gpu?.[0]?.name ?? 'Integrated') : '…' },
    { key: 'vram_gb', label: 'Graphics memory', value: hardware ? (hardware.vram_gb ? `${hardware.vram_gb} GB` : 'Shared') : '…' },
  ]

  const hasError = hardwareError || planError
  const canContinue = done && !!plan && !hasError

  return (
    <div>
      <StepCounter current={1} total={3} />
      <h2 className="mt-3 text-[22px] font-semibold tracking-tight text-(--ink)">Checking your machine</h2>
      <p className="mt-2 text-[14px] text-(--ink-muted) leading-relaxed">
        We'll read what you've got and pick models that fit. This takes a few seconds and you only do it once.
      </p>

      <div className="mt-8 rounded-xl border border-(--border) bg-(--surface) divide-y divide-(--border)">
        {rows.map((r, i) => (
          <HardwareRow key={r.key} label={r.label} value={r.value} hasData={!!hardware} index={i} />
        ))}
      </div>

      {canContinue && plan && (
        <PlanPreview plan={plan} />
      )}

      {hasError && (
        <div className="mt-5 flex items-center justify-between gap-3 rounded-lg border border-red-500/30 bg-red-500/5 px-4 py-3">
          <div className="flex items-center gap-2 text-[13px] text-red-600 dark:text-red-400">
            <AlertCircle className="w-4 h-4 shrink-0" />
            {hardwareError
              ? 'Could not read your hardware. Check that the backend is running.'
              : 'Could not resolve a model plan for your hardware.'}
          </div>
          <button
            onClick={onRetry}
            className="shrink-0 text-[13px] font-medium text-(--accent) hover:underline"
          >
            Retry
          </button>
        </div>
      )}

      {!done && !hasError && (
        <div className="mt-5 flex items-center gap-2 text-[13px] text-(--ink-muted)">
          <RefreshCw className="w-3.5 h-3.5 animate-spin" /> Scanning…
        </div>
      )}

      {done && !hasError && !plan && (
        <div className="mt-5 flex items-center gap-2 text-[13px] text-(--ink-muted)">
          <RefreshCw className="w-3.5 h-3.5 animate-spin" /> Resolving plan…
        </div>
      )}

      <div className="mt-8 flex items-center justify-between">
        <Button variant="ghost" onClick={onBack}>Back</Button>
        <Button onClick={onNext} disabled={!canContinue}>Continue</Button>
      </div>
    </div>
  )
}
