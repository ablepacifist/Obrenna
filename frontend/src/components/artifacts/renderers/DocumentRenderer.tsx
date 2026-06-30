import type { DocumentArtifact } from '../../../lib/types/artifact'
import { MarkdownContent } from '../../chat/MarkdownContent'

interface DocumentRendererProps {
  artifact: DocumentArtifact
}

export function DocumentRenderer({ artifact }: DocumentRendererProps) {
  return (
    <div className="max-w-[680px] mx-auto rounded-xl border border-(--border) bg-(--surface) p-8">
      <article className="text-[14px] text-(--ink)">
        <MarkdownContent>{artifact.spec.markdown}</MarkdownContent>
      </article>
    </div>
  )
}
