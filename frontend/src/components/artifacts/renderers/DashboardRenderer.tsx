import {
  Area, AreaChart, Bar, BarChart, CartesianGrid,
  Legend, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { cn } from '../../../lib/cn'
import type { DashboardArtifact } from '../../../lib/types/artifact'

interface DashboardRendererProps {
  artifact: DashboardArtifact
}

export function DashboardRenderer({ artifact }: DashboardRendererProps) {
  const { spec } = artifact

  return (
    <div className="max-w-[880px] mx-auto space-y-5">
      {/* KPI cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {spec.cards.map((k, i) => (
          <div key={i} className="rounded-xl border border-(--border) bg-(--surface) p-4">
            <div className="text-[11px] uppercase tracking-wide text-(--ink-faint)">{k.label}</div>
            <div className="mt-1.5 text-[22px] font-semibold tracking-tight text-(--ink) tabular-nums">{k.value}</div>
            {k.delta && (
              <div className={cn('text-[12px] mt-0.5', k.trend === 'up' ? 'text-(--ok)' : k.trend === 'down' ? 'text-(--err)' : 'text-(--ink-muted)')}>
                {k.delta}
              </div>
            )}
            {k.description && <div className="text-[11px] text-(--ink-faint) mt-0.5">{k.description}</div>}
          </div>
        ))}
      </div>

      {/* Charts */}
      {spec.charts.length > 0 && (
        <div className={cn('grid gap-3', spec.charts.length === 1 ? 'grid-cols-1' : 'grid-cols-1 md:grid-cols-2')}>
          {spec.charts.map((ch, i) => {
            const data = ch.x.map((label, xi) => ({
              label,
              ...Object.fromEntries(ch.series.map(s => [s.name, s.data[xi] ?? 0])),
            }))
            return (
              <div key={i} className="rounded-xl border border-(--border) bg-(--surface) p-4">
                <div className="text-[13px] font-medium text-(--ink)">{ch.title}</div>
                <div className="mt-4 h-[220px]">
                  <ResponsiveContainer width="100%" height="100%">
                    {ch.type === 'area' ? (
                      <AreaChart data={data}>
                        <CartesianGrid stroke="var(--border)" vertical={false} />
                        <XAxis dataKey="label" tick={{ fontSize: 11, fill: 'currentColor' }} stroke="var(--border)" />
                        <YAxis tick={{ fontSize: 11, fill: 'currentColor' }} stroke="var(--border)" />
                        <Tooltip contentStyle={{ background: 'var(--surface)', border: '1px solid var(--border)', fontSize: 12, borderRadius: 8 }} />
                        {ch.series.map((s, si) => (
                          <Area key={si} type="monotone" dataKey={s.name} stroke="var(--accent)" fill="var(--accent)" fillOpacity={0.15} />
                        ))}
                      </AreaChart>
                    ) : (
                      <BarChart data={data}>
                        <CartesianGrid stroke="var(--border)" vertical={false} />
                        <XAxis dataKey="label" tick={{ fontSize: 11, fill: 'currentColor' }} stroke="var(--border)" />
                        <YAxis tick={{ fontSize: 11, fill: 'currentColor' }} stroke="var(--border)" />
                        <Tooltip contentStyle={{ background: 'var(--surface)', border: '1px solid var(--border)', fontSize: 12, borderRadius: 8 }} />
                        {ch.series.length > 1 && <Legend wrapperStyle={{ fontSize: 11 }} />}
                        {ch.series.map((s, si) => (
                          <Bar key={si} dataKey={s.name} fill={si === 0 ? 'var(--accent)' : 'var(--border-strong)'} radius={[4, 4, 0, 0]} />
                        ))}
                      </BarChart>
                    )}
                  </ResponsiveContainer>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* Tables */}
      {spec.tables.map((t, i) => (
        <div key={i} className="rounded-xl border border-(--border) bg-(--surface) overflow-hidden">
          <div className="px-4 py-3 border-b border-(--border)">
            <div className="text-[13px] font-medium text-(--ink)">{t.title}</div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-[13px]">
              <thead className="bg-(--surface-2) text-(--ink-muted) text-[11px] uppercase tracking-wide">
                <tr>{t.columns.map(h => <th key={h} className="text-left font-medium px-4 py-2">{h}</th>)}</tr>
              </thead>
              <tbody className="text-(--ink)">
                {t.rows.map((r, ri) => (
                  <tr key={ri} className="border-t border-(--border)">
                    {r.map((c, ci) => <td key={ci} className="px-4 py-2.5 tabular-nums">{c}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ))}

      {/* Insights */}
      {spec.insights.length > 0 && (
        <div className="rounded-xl border border-(--border) bg-(--surface) p-4">
          <div className="text-[13px] font-medium text-(--ink) mb-2">Insights</div>
          <ul className="space-y-1">
            {spec.insights.map((ins, i) => (
              <li key={i} className="text-[13px] text-(--ink-muted) flex gap-2">
                <span className="text-(--ink-faint) shrink-0">—</span>
                <span>{ins}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
