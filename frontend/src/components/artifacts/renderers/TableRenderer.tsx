import type { TableArtifact } from '../../../lib/types/artifact'

interface TableRendererProps {
  artifact: TableArtifact
}

export function TableRenderer({ artifact }: TableRendererProps) {
  const t = artifact.spec.table
  return (
    <div className="max-w-[880px] mx-auto rounded-xl border border-(--border) bg-(--surface) overflow-hidden">
      <div className="px-5 py-4 border-b border-(--border)">
        <div className="text-[15px] font-medium text-(--ink)">{artifact.title}</div>
        {artifact.summary && <div className="text-[12px] text-(--ink-muted) mt-0.5">{artifact.summary}</div>}
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-[13px]">
          <thead className="bg-(--surface-2) text-(--ink-muted) text-[11px] uppercase tracking-wide">
            <tr>
              {t.columns.map(h => (
                <th key={h} className="text-left font-medium px-4 py-2.5">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="text-(--ink)">
            {t.rows.map((r, i) => (
              <tr key={i} className="border-t border-(--border)">
                {r.map((c, j) => (
                  <td key={j} className="px-4 py-2.5 tabular-nums">{c}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
