import { useEffect, useState } from 'react'
import { getModelStatus, type ModelStatus } from '../../lib/api'

export function ModelsSettings() {
  const [status, setStatus] = useState<ModelStatus | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getModelStatus()
      .then(setStatus)
      .catch(() => setStatus(null))
      .finally(() => setLoading(false))
  }, [])

  return (
    <div>
      <h3 className="text-[18px] font-semibold tracking-tight text-(--ink)">Active models</h3>
      <p className="mt-1 text-[13px] text-(--ink-muted) leading-relaxed">
        Models assigned to your hardware tier. Green means the model is available at your configured runtime.
      </p>

      <div className="mt-5 rounded-xl border border-(--border) bg-(--surface) divide-y divide-(--border)">
        {loading && (
          <div className="p-4 text-[13px] text-(--ink-muted)">Checking models…</div>
        )}

        {!loading && !status?.connected && (
          <div className="p-4 text-[13px] text-(--warn)">
            Runtime unreachable — start your local model server to see status.
            {status?.error && <div className="mt-1 text-(--ink-muted) text-[11px] break-words">{status.error}</div>}
          </div>
        )}

        {!loading && status?.connected && status.roles.length === 0 && (
          <div className="p-4 text-[13px] text-(--ink-muted)">No models configured. Go to Setup to choose models.</div>
        )}

        {status?.roles.map(r => (
          <div key={r.role} className="p-4 flex items-center justify-between gap-4">
            <div>
              <div className="text-[14px] font-medium text-(--ink)">{r.display_name}</div>
              <div className="mt-0.5 text-[12px] text-(--ink-muted)">{r.label}</div>
            </div>
            <span className={`text-[12px] font-medium ${r.available ? 'text-(--ok)' : 'text-(--ink-muted)'}`}>
              {r.available ? '✓ Loaded' : 'Not loaded'}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}
