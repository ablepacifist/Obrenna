import type { ReportArtifact } from '../../../lib/types/artifact'

interface ReportRendererProps {
  artifact: ReportArtifact
}

export function ReportRenderer({ artifact }: ReportRendererProps) {
  const { spec, title } = artifact
  return (
    <div className="max-w-[680px] mx-auto">
      <div className="rounded-xl border border-(--border) bg-(--surface) shadow-[var(--shadow)] overflow-hidden">
        <div className="p-10">
          {(spec.prepared || spec.prepared_for || spec.prepared_by) && (
            <div className="flex items-start justify-between mb-8">
              <div>
                {spec.prepared_by && <div className="text-[11px] uppercase tracking-wide text-(--ink-faint)">{spec.prepared_by}</div>}
                {spec.prepared && <div className="mt-0.5 text-[12px] text-(--ink-muted)">Prepared {spec.prepared}</div>}
              </div>
              {spec.prepared_for && (
                <div className="text-right">
                  <div className="text-[11px] uppercase tracking-wide text-(--ink-faint)">Prepared for</div>
                  <div className="mt-0.5 text-[12px] text-(--ink)">{spec.prepared_for}</div>
                </div>
              )}
            </div>
          )}
          <h1 className="text-[22px] font-semibold tracking-tight text-(--ink) leading-tight">{title}</h1>
          {spec.sections.map((s, i) => (
            <div key={i} className="mt-8">
              <h2 className="text-[15px] font-semibold text-(--ink)">{s.heading}</h2>
              {s.paragraphs.map((p, j) => (
                <p key={j} className="mt-2 text-[13px] text-(--ink) leading-relaxed">{p}</p>
              ))}
              {s.table && (
                <div className="mt-4 rounded-md border border-(--border) overflow-hidden">
                  <table className="w-full text-[12px]">
                    <thead className="bg-(--surface-2) text-(--ink-muted)">
                      <tr>{s.table.columns.map(h => <th key={h} className="text-left font-medium px-3 py-2">{h}</th>)}</tr>
                    </thead>
                    <tbody className="text-(--ink)">
                      {s.table.rows.map((r, j) => (
                        <tr key={j} className="border-t border-(--border)">
                          {r.map((c, k) => <td key={k} className="px-3 py-2">{c}</td>)}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
