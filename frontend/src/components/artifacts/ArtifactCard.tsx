import { useState } from 'react'
import { ChevronDown, ChevronRight, PanelRight } from 'lucide-react'
import type { Artifact } from '../../lib/types/artifact'
import { IconButton } from '../ui/IconButton'
import { ArtifactIcon } from './ArtifactIcon'
import { ArtifactPreview } from './ArtifactPreview'

interface ArtifactCardProps {
  artifact: Artifact
  onOpen: () => void
}

export function ArtifactCard({ artifact, onOpen }: ArtifactCardProps) {
  const [expanded, setExpanded] = useState(true)
  return (
    <div className="rounded-xl border border-(--border) bg-(--surface) overflow-hidden">
      <div className="h-11 px-3 flex items-center justify-between gap-2 border-b border-(--border)">
        <button
          onClick={() => setExpanded(v => !v)}
          className="flex items-center gap-2 min-w-0 text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-(--accent) rounded"
        >
          {expanded
            ? <ChevronDown className="w-3.5 h-3.5 text-(--ink-faint) shrink-0" />
            : <ChevronRight className="w-3.5 h-3.5 text-(--ink-faint) shrink-0" />}
          <ArtifactIcon type={artifact.artifact_type} className="w-3.5 h-3.5 text-(--accent) shrink-0" />
          <span className="text-[13px] font-medium text-(--ink) truncate">{artifact.title}</span>
          <span className="text-[11px] uppercase tracking-wide text-(--ink-faint)">{artifact.artifact_type}</span>
        </button>
        <IconButton onClick={onOpen} title="Open in side panel">
          <PanelRight className="w-4 h-4" />
        </IconButton>
      </div>
      {expanded && (
        <div className="p-3">
          <ArtifactPreview artifact={artifact} />
        </div>
      )}
    </div>
  )
}
