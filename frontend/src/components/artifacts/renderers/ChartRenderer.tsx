import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Legend,
  Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import type { ChartArtifact } from '../../../lib/types/artifact'

interface ChartRendererProps {
  artifact: ChartArtifact
}

export function ChartRenderer({ artifact }: ChartRendererProps) {
  const ch = artifact.spec.chart
  const data = ch.x.map((label, xi) => ({
    label,
    ...Object.fromEntries(ch.series.map(s => [s.name, s.data[xi] ?? 0])),
  }))

  const tooltip = { contentStyle: { background: 'var(--surface)', border: '1px solid var(--border)', fontSize: 12, borderRadius: 8 } }

  return (
    <div className="max-w-[760px] mx-auto rounded-xl border border-(--border) bg-(--surface) p-5">
      <div className="text-[15px] font-medium text-(--ink)">{artifact.title}</div>
      {artifact.summary && <div className="text-[12px] text-(--ink-muted) mt-0.5">{artifact.summary}</div>}
      <div className="mt-5 h-[340px]">
        <ResponsiveContainer width="100%" height="100%">
          {ch.type === 'area' ? (
            <AreaChart data={data}>
              <CartesianGrid stroke="var(--border)" vertical={false} />
              <XAxis dataKey="label" tick={{ fontSize: 11, fill: 'currentColor' }} stroke="var(--border)" />
              <YAxis tick={{ fontSize: 11, fill: 'currentColor' }} stroke="var(--border)" />
              <Tooltip {...tooltip} />
              {ch.series.length > 1 && <Legend wrapperStyle={{ fontSize: 12 }} />}
              {ch.series.map((s, i) => (
                <Area key={i} type="monotone" dataKey={s.name} stroke="var(--accent)" fill="var(--accent)" fillOpacity={0.15} />
              ))}
            </AreaChart>
          ) : ch.type === 'line' ? (
            <LineChart data={data}>
              <CartesianGrid stroke="var(--border)" vertical={false} />
              <XAxis dataKey="label" tick={{ fontSize: 11, fill: 'currentColor' }} stroke="var(--border)" />
              <YAxis tick={{ fontSize: 11, fill: 'currentColor' }} stroke="var(--border)" />
              <Tooltip {...tooltip} />
              {ch.series.length > 1 && <Legend wrapperStyle={{ fontSize: 12 }} />}
              {ch.series.map((s, i) => (
                <Line key={i} type="monotone" dataKey={s.name} stroke="var(--accent)" dot={false} />
              ))}
            </LineChart>
          ) : (
            <BarChart data={data}>
              <CartesianGrid stroke="var(--border)" vertical={false} />
              <XAxis dataKey="label" tick={{ fontSize: 11, fill: 'currentColor' }} stroke="var(--border)" />
              <YAxis tick={{ fontSize: 11, fill: 'currentColor' }} stroke="var(--border)" />
              <Tooltip {...tooltip} />
              {ch.series.length > 1 && <Legend wrapperStyle={{ fontSize: 12 }} />}
              {ch.series.map((s, i) => (
                <Bar key={i} dataKey={s.name} fill={i === 0 ? 'var(--accent)' : 'var(--border-strong)'} radius={[4, 4, 0, 0]} />
              ))}
            </BarChart>
          )}
        </ResponsiveContainer>
      </div>
    </div>
  )
}
