import { Copy, Download, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import type { Artifact } from '../../lib/types/artifact'
import { getArtifact, exportPdf, downloadPdfUrl } from '../../lib/api'
import { IconButton } from '../ui/IconButton'
import { ArtifactIcon } from './ArtifactIcon'
import { ArtifactFull } from './ArtifactFull'

interface ArtifactPanelProps {
  artifactId: string
  onClose: () => void
  onResizeStart: (e: React.MouseEvent) => void
}

export function ArtifactPanel({ artifactId, onClose, onResizeStart }: ArtifactPanelProps) {
  const [artifact, setArtifact] = useState<Artifact | null>(null)
  const [exporting, setExporting] = useState(false)

  useEffect(() => {
    setArtifact(null)
    getArtifact(artifactId)
      .then(r => setArtifact(r.artifact as unknown as Artifact))
      .catch(() => {})
  }, [artifactId])

  const handleDownload = async () => {
    if (!artifact) return
    setExporting(true)
    try {
      await exportPdf(artifactId)
      window.open(downloadPdfUrl(artifactId), '_blank')
    } catch {
      // silently fail — PDF may not be available
    } finally {
      setExporting(false)
    }
  }

  const handleCopy = () => {
    if (!artifact) return
    const text = JSON.stringify(artifact, null, 2)
    navigator.clipboard.writeText(text).catch(() => {})
  }

  return (
    <>
      <div
        onMouseDown={onResizeStart}
        className="absolute top-0 left-0 w-1 h-full cursor-col-resize hover:bg-(--accent)/30 active:bg-(--accent)/50 z-10"
      />
      <div className="h-full flex flex-col bg-(--bg)">
        <header className="h-12 border-b border-(--border) px-4 flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0">
            {artifact && (
              <>
                <ArtifactIcon type={artifact.artifact_type} className="w-4 h-4 text-(--accent) shrink-0" />
                <div className="min-w-0">
                  <div className="text-[13px] font-medium text-(--ink) truncate">{artifact.title}</div>
                  <div className="text-[11px] text-(--ink-faint) uppercase tracking-wide">{artifact.artifact_type}</div>
                </div>
              </>
            )}
            {!artifact && <div className="text-[13px] text-(--ink-muted)">Loading…</div>}
          </div>
          <div className="flex items-center gap-0.5">
            <IconButton title="Copy as JSON" onClick={handleCopy}><Copy className="w-4 h-4" /></IconButton>
            <IconButton title="Export PDF" onClick={handleDownload} disabled={exporting || !artifact}>
              <Download className="w-4 h-4" />
            </IconButton>
            <IconButton onClick={onClose} title="Close panel"><X className="w-4 h-4" /></IconButton>
          </div>
        </header>
        <div className="flex-1 overflow-y-auto p-6">
          {artifact && <ArtifactFull artifact={artifact} />}
        </div>
      </div>
    </>
  )
}
