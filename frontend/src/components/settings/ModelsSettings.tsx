import { useEffect, useState } from 'react'
import { type CatalogModel, getModelCatalog, getAppSettings } from '../../lib/api'
import { FitBadge } from '../ui/FitBadge'

export function ModelsSettings() {
  const [catalog, setCatalog] = useState<CatalogModel[]>([])
  const [activeIds, setActiveIds] = useState<string[]>([])

  useEffect(() => {
    Promise.all([getModelCatalog(), getAppSettings()]).then(([cat, settings]) => {
      setCatalog(cat)
      setActiveIds(settings.active_models)
    }).catch(() => {})
  }, [])

  const active = catalog.filter(m => activeIds.includes(m.id))
  const others = catalog.filter(m => !activeIds.includes(m.id))

  return (
    <div>
      <h3 className="text-[18px] font-semibold tracking-tight text-(--ink)">Active models</h3>
      <p className="mt-1 text-[13px] text-(--ink-muted) leading-relaxed">
        These are the models configured for this workspace. The indicator shows whether each one fits your hardware.
      </p>
      <div className="mt-5 rounded-xl border border-(--border) bg-(--surface) divide-y divide-(--border)">
        {active.map(m => (
          <div key={m.id} className="p-4 flex items-center justify-between gap-4">
            <div>
              <div className="text-[14px] font-medium text-(--ink)">{m.name}</div>
              <div className="mt-0.5 text-[12px] text-(--ink-muted)">{m.role} · {m.size}</div>
            </div>
            <FitBadge fit={m.fit} note={m.note} />
          </div>
        ))}
        {active.length === 0 && (
          <div className="p-4 text-[13px] text-(--ink-muted)">No active models configured. Go to Setup to choose models.</div>
        )}
      </div>

      {others.length > 0 && (
        <>
          <h4 className="mt-8 text-[14px] font-medium text-(--ink)">Other models considered</h4>
          <div className="mt-3 rounded-xl border border-(--border) bg-(--surface) divide-y divide-(--border)">
            {others.map(m => (
              <div key={m.id} className="p-4 flex items-center justify-between gap-4">
                <div>
                  <div className="text-[14px] font-medium text-(--ink)">{m.name}</div>
                  <div className="mt-0.5 text-[12px] text-(--ink-muted)">{m.size}</div>
                </div>
                <FitBadge fit={m.fit} note={m.note} />
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
