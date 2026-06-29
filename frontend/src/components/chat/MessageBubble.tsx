import { FileText, Sparkles } from 'lucide-react'
import { useEffect, useState } from 'react'
import type { Artifact } from '../../lib/types/artifact'
import type { ChatMessageDTO } from '../../lib/api'
import { getArtifact } from '../../lib/api'
import { ArtifactCard } from '../artifacts/ArtifactCard'
import { StreamedText } from './StreamedText'

interface MessageBubbleProps {
  msg: ChatMessageDTO
  onOpenArtifact: (id: string) => void
  isLatestAssistant: boolean
}

export function MessageBubble({ msg, onOpenArtifact, isLatestAssistant }: MessageBubbleProps) {
  const [artifacts, setArtifacts] = useState<Record<string, Artifact>>({})

  useEffect(() => {
    if (!msg.artifacts?.length) return
    msg.artifacts.forEach(id => {
      getArtifact(id)
        .then(r => setArtifacts(prev => ({ ...prev, [id]: r.artifact as unknown as Artifact })))
        .catch(() => {})
    })
  }, [msg.artifacts])

  if (msg.role === 'user') {
    return (
      <div className="flex justify-end">
        <div className="max-w-[640px]">
          <div className="text-[14px] text-(--ink) leading-relaxed whitespace-pre-wrap">{msg.text}</div>
          {msg.files?.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {msg.files.map((f, i) => (
                <span key={i} className="inline-flex items-center gap-1.5 h-7 px-2 rounded-md bg-(--surface-2) border border-(--border) text-[12px] text-(--ink-muted)">
                  <FileText className="w-3 h-3" /> {f.name}
                  <span className="text-(--ink-faint)">· {Math.round(f.size / 1024)} KB</span>
                </span>
              ))}
            </div>
          )}
        </div>
      </div>
    )
  }

  return (
    <div className="flex gap-3">
      <div className="w-6 h-6 rounded-md bg-(--surface-2) border border-(--border) flex items-center justify-center shrink-0 mt-0.5">
        <Sparkles className="w-3 h-3 text-(--accent)" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="text-[14px] text-(--ink) leading-relaxed whitespace-pre-wrap">
          <StreamedText text={msg.text} active={isLatestAssistant} />
        </div>
        {msg.artifacts?.length > 0 && (
          <div className="mt-4 space-y-2.5">
            {msg.artifacts.map(id => {
              const a = artifacts[id]
              if (!a) return null
              return (
                <ArtifactCard key={id} artifact={a} onOpen={() => onOpenArtifact(id)} />
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
