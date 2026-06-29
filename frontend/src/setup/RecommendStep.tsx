import { BadgeCheck, Cpu, HardDrive, Monitor, WifiOff } from 'lucide-react'
import { Button } from '../components/ui/Button'
import { StepCounter } from '../components/ui/StepCounter'
import type { ManagedPlan } from '../lib/api'

interface RecommendStepProps {
  plan: ManagedPlan
  onNext: () => void
  onBack: () => void
  onConfirm: () => void
  confirmed: boolean
}

function TierBadge({ plan }: { plan: ManagedPlan }) {
  const colorMap: Record<string, string> = {
    gpu: 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200',
    apple: 'bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200',
    cpu_only: 'bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200',
    reject: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200',
  }
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[11px] font-medium tracking-wide uppercase ${colorMap[plan.path] || 'bg-gray-100 text-gray-800'}`}>
      {plan.path === 'gpu' && <Monitor className="w-3 h-3" />}
      {plan.path === 'apple' && <BadgeCheck className="w-3 h-3" />}
      {plan.path === 'cpu_only' && <Cpu className="w-3 h-3" />}
      {plan.path === 'reject' && <WifiOff className="w-3 h-3" />}
      {plan.plan_id || plan.path}
    </span>
  )
}

function ModelRow({ label, model }: { label: string; model?: { model: string; quant: string; device: string } | null }) {
  if (!model) return null
  return (
    <div className="flex items-center justify-between text-[13px] py-1.5">
      <span className="text-(--ink-muted)">{label}</span>
      <span className="font-medium text-(--ink)">
        {model.model} <span className="text-(--ink-muted) font-normal">{model.quant}</span>
        {model.device !== 'gpu' && <span className="text-(--ink-muted) ml-1 text-[11px]">({model.device})</span>}
      </span>
    </div>
  )
}

export function RecommendStep({ plan, onNext, onBack, onConfirm, confirmed }: RecommendStepProps) {
  const isReject = plan.path === 'reject'

  return (
    <div>
      <StepCounter current={2} total={3} />
      <h2 className="mt-3 text-[22px] font-semibold tracking-tight text-(--ink)">
        {isReject ? 'Bring your own server' : 'Recommended setup'}
      </h2>
      <p className="mt-2 text-[14px] text-(--ink-muted) leading-relaxed">
        {isReject
          ? plan.reason || 'Your machine does not meet the requirements for a managed local setup.'
          : `We detected a ${plan.path === 'gpu' ? 'discrete GPU' : plan.path === 'apple' ? 'Apple Silicon' : 'CPU-only machine'}. Here is the plan that fits.`}
      </p>

      <div className="mt-6 p-4 rounded-xl border border-(--border) bg-(--surface)">
        <div className="flex items-center justify-between mb-3">
          <TierBadge plan={plan} />
          {plan.plan_rank !== undefined && (
            <span className="text-[11px] text-(--ink-muted)">Rank {plan.plan_rank}</span>
          )}
        </div>

        {!isReject && (
          <>
            <div className="space-y-0.5">
              <ModelRow label="Orchestrator" model={plan.orchestrator} />
              <ModelRow label="Summarizer" model={plan.summarizer} />
              <ModelRow label="Utility" model={plan.utility} />
            </div>

            <div className="mt-3 pt-3 border-t border-(--border) space-y-1">
              <div className="flex items-center justify-between text-[13px] py-0.5">
                <span className="text-(--ink-muted) flex items-center gap-1">
                  <HardDrive className="w-3.5 h-3.5" />
                  Context length
                </span>
                <span className="font-medium text-(--ink)">{plan.ctx ? `${plan.ctx.toLocaleString()} tokens` : '—'}</span>
              </div>
              <div className="flex items-center justify-between text-[13px] py-0.5">
                <span className="text-(--ink-muted)">Helper workers</span>
                <span className="font-medium text-(--ink)">{plan.helper_count}</span>
              </div>
              {plan.runtime_priority.length > 0 && (
                <div className="flex items-center justify-between text-[13px] py-0.5">
                  <span className="text-(--ink-muted)">Runtime priority</span>
                  <span className="font-medium text-(--ink)">{plan.runtime_priority.join(', ')}</span>
                </div>
              )}
              {plan.runtime_forbidden.length > 0 && (
                <div className="flex items-center justify-between text-[13px] py-0.5">
                  <span className="text-(--ink-muted) text-red-600 dark:text-red-400">Runtime forbidden</span>
                  <span className="font-medium text-(--ink-muted)">{plan.runtime_forbidden.join(', ')}</span>
                </div>
              )}
            </div>

            {plan.detection_warnings.length > 0 && (
              <div className="mt-3 pt-3 border-t border-(--border)">
                <details className="text-[12px] text-(--ink-muted)">
                  <summary className="cursor-pointer hover:text-(--ink)">Detection notes</summary>
                  <ul className="mt-1 space-y-0.5 list-disc list-inside">
                    {plan.detection_warnings.map((w, i) => (
                      <li key={i}>{w}</li>
                    ))}
                  </ul>
                </details>
              </div>
            )}
          </>
        )}
      </div>

      {isReject && (
        <div className="mt-6 p-4 rounded-xl border border-(--border) bg-(--surface-2)">
          <div className="text-[13px] text-(--ink-muted) leading-relaxed">
            Connect to an Ollama, LM Studio, llama.cpp, or any OpenAI-compatible server you already run locally.
          </div>
        </div>
      )}

      <div className="mt-8 flex items-center justify-between">
        <Button variant="ghost" onClick={onBack}>Back</Button>
        <Button onClick={isReject ? onNext : (confirmed ? onNext : onConfirm)}>
          {isReject ? 'Connect server' : confirmed ? 'Continue' : 'Confirm plan'}
        </Button>
      </div>
    </div>
  )
}
