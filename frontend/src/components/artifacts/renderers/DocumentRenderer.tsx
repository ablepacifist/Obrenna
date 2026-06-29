import type { DocumentArtifact } from '../../../lib/types/artifact'

interface DocumentRendererProps {
  artifact: DocumentArtifact
}

export function DocumentRenderer({ artifact }: DocumentRendererProps) {
  const lines = artifact.spec.markdown.split('\n')
  return (
    <div className="max-w-[680px] mx-auto rounded-xl border border-(--border) bg-(--surface) p-8">
      <article>
        {lines.map((line, i) => {
          if (line.startsWith('## '))
            return <h2 key={i} className="text-[17px] font-semibold text-(--ink) mt-6 mb-2 first:mt-0">{line.slice(3)}</h2>
          if (line.startsWith('# '))
            return <h2 key={i} className="text-[17px] font-semibold text-(--ink) mt-6 mb-2 first:mt-0">{line.slice(2)}</h2>
          if (line.startsWith('- **')) {
            const m = line.match(/^- \*\*(.+?)\*\* — (.+)$/) ?? line.match(/^- \*\*(.+?)\*\*(.*)$/)
            if (m)
              return (
                <div key={i} className="flex gap-2 py-1 text-[13px] text-(--ink) leading-relaxed">
                  <span className="text-(--ink-faint) shrink-0">—</span>
                  <span><span className="font-medium">{m[1]}</span>{m[2]}</span>
                </div>
              )
          }
          if (line.startsWith('- '))
            return (
              <div key={i} className="flex gap-2 py-0.5 text-[13px] text-(--ink) leading-relaxed">
                <span className="text-(--ink-faint) shrink-0">—</span>
                <span>{line.slice(2)}</span>
              </div>
            )
          if (line.trim() === '') return <div key={i} className="h-2" />
          return <p key={i} className="text-[13px] text-(--ink) leading-relaxed">{line}</p>
        })}
      </article>
    </div>
  )
}
