export type ActivityStep = {
  key: string
  label: string
  status: 'pending' | 'running' | 'done' | 'error'
  detail?: string
}

export function ActivityStrip({ steps }: { steps: ActivityStep[] }) {
  if (!steps.length) return null

  return (
    <div className="mt-2 space-y-1 text-[12px] text-(--ink-muted)">
      {steps.slice(-4).map(step => (
        <div key={step.key} className="flex items-center gap-2">
          <span className="w-3 text-center">
            {step.status === 'done'
              ? '✓'
              : step.status === 'running'
                ? '•'
                : step.status === 'error'
                  ? '!'
                  : '○'}
          </span>
          <span>{step.label}</span>
          {step.detail && <span className="opacity-70">{step.detail}</span>}
        </div>
      ))}
    </div>
  )
}
