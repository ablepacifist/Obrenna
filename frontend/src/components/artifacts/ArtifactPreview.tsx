import type { Artifact } from '../../lib/types/artifact'

interface ArtifactPreviewProps {
  artifact: Artifact
}

export function ArtifactPreview({ artifact }: ArtifactPreviewProps) {
  const a = artifact

  if (a.artifact_type === 'dashboard') {
    return (
      <div className="grid grid-cols-2 gap-2">
        {a.spec.cards.slice(0, 4).map((k, i) => (
          <div key={i} className="rounded-md bg-(--surface-2) border border-(--border) p-2.5">
            <div className="text-[10px] text-(--ink-faint) uppercase tracking-wide">{k.label}</div>
            <div className="mt-1 text-[15px] font-semibold text-(--ink) tabular-nums">{k.value}</div>
            {k.delta && <div className="text-[10px] mt-0.5 text-(--ok)">{k.delta}</div>}
          </div>
        ))}
      </div>
    )
  }

  if (a.artifact_type === 'report') {
    return (
      <div className="rounded-md bg-(--surface-2) border border-(--border) p-4 flex flex-col gap-2">
        <div className="text-[11px] uppercase tracking-wide text-(--ink-faint)">Report</div>
        <div className="text-[13px] font-medium text-(--ink) leading-snug">{a.title}</div>
        <div className="space-y-1.5 mt-1">
          {[0, 1, 2, 3].map(i => (
            <div key={i} className="h-1.5 rounded-full bg-(--border-strong)" style={{ width: `${88 - i * 12}%` }} />
          ))}
        </div>
      </div>
    )
  }

  if (a.artifact_type === 'chart') {
    const ch = a.spec.chart
    return (
      <div className="rounded-md bg-(--surface-2) border border-(--border) p-3">
        <div className="text-[12px] font-medium text-(--ink) mb-2">{ch.title}</div>
        <div className="flex items-end gap-1 h-[80px]">
          {ch.series[0]?.data.slice(0, 8).map((v, i) => {
            const max = Math.max(...(ch.series[0]?.data ?? [1]))
            const pct = max > 0 ? (v / max) * 100 : 0
            return (
              <div key={i} className="flex-1 bg-(--accent) rounded-sm" style={{ height: `${pct}%`, opacity: 0.8 }} />
            )
          })}
        </div>
      </div>
    )
  }

  if (a.artifact_type === 'table') {
    const t = a.spec.table
    return (
      <div className="max-h-[160px] overflow-auto rounded-md border border-(--border)">
        <table className="w-full text-[12px]">
          <thead className="bg-(--surface-2) text-(--ink-muted)">
            <tr>{t.columns.map(h => <th key={h} className="text-left font-medium px-2.5 py-1.5">{h}</th>)}</tr>
          </thead>
          <tbody className="text-(--ink)">
            {t.rows.slice(0, 5).map((r, i) => (
              <tr key={i} className="border-t border-(--border)">
                {r.map((c, j) => <td key={j} className="px-2.5 py-1.5 tabular-nums">{c}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )
  }

  if (a.artifact_type === 'document') {
    return (
      <div className="text-[12px] text-(--ink) leading-relaxed max-h-[160px] overflow-auto space-y-1">
        {a.spec.markdown.split('\n').slice(0, 8).map((l, i) => (
          <div key={i} className={l.startsWith('##') ? 'font-medium text-[13px]' : 'text-(--ink-muted)'}>
            {l || ' '}
          </div>
        ))}
        <div className="text-(--ink-faint) text-[11px]">… continued in side panel</div>
      </div>
    )
  }

  return null
}
