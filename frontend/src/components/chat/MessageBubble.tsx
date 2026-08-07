import { ExternalLink, FileText } from 'lucide-react'
import { useEffect, useState } from 'react'
import type { Artifact } from '../../lib/types/artifact'
import type { ChatMessageDTO } from '../../lib/api'
import { getArtifact } from '../../lib/api'
import { ArtifactCard } from '../artifacts/ArtifactCard'
import { MarkdownContent } from './MarkdownContent'
import { ThinkingPane } from './ThinkingPane'
import { ToolCallCard } from './ToolCallCard'
import { useTheme } from '../../theme/ThemeProvider'
import ObrennaMono from '../../assets/logos/ObrennaMono.png'
import ObrennaMonoWhite from '../../assets/logos/ObrennaMonoWhite.png'

interface SourceItem {
  title: string
  url: string
  snippet: string
}

interface ExtendedChatMessageDTO extends ChatMessageDTO {
  sources?: SourceItem[]
  // Ephemeral, UI-only fields for the in-flight assistant message.
  // Not persisted — never present on messages loaded from the API.
  thinking?: string
  thinkingExpanded?: boolean
  onThinkingExpandedChange?: (expanded: boolean) => void
}

interface MessageBubbleProps {
  msg: ExtendedChatMessageDTO
  onOpenArtifact: (id: string) => void
  isLatestAssistant: boolean
}

export function MessageBubble({ msg, onOpenArtifact }: MessageBubbleProps) {
  const { resolvedTheme } = useTheme()
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
      <img
        src={resolvedTheme === 'dark' ? ObrennaMonoWhite : ObrennaMono}
        alt="Obrenna"
        className="w-5 h-5 object-contain shrink-0 mt-0.5"
      />
      <div className="min-w-0 flex-1">
        {msg.thinking ? (
          <ThinkingPane
            text={msg.thinking}
            expanded={msg.thinkingExpanded ?? false}
            onExpandedChange={msg.onThinkingExpandedChange ?? (() => {})}
          />
        ) : null}
        <div className="text-[14px] text-(--ink)">
          {msg.blocks && msg.blocks.length > 0 ? (
            <div className="space-y-2">
              {/* Only text and tool blocks are persisted. Approval/question
                  blocks are live-only prompts — once decided they're part of
                  the tool card's own record, so there's nothing to replay. */}
              {msg.blocks.map((b, i) =>
                b.kind === 'text' ? (
                  <MarkdownContent key={i}>{b.text}</MarkdownContent>
                ) : b.kind === 'tool' ? (
                  <ToolCallCard key={i} block={b} />
                ) : null,
              )}
            </div>
          ) : (
            <MarkdownContent>{msg.text ?? ''}</MarkdownContent>
          )}
        </div>
        {/* Source citations */}
        {msg.sources && msg.sources.length > 0 && (
          <div className="mt-3 space-y-1.5">
            <div className="text-[11px] text-(--ink-faint) uppercase tracking-wider font-medium">Sources</div>
            <div className="space-y-1.5">
              {msg.sources.map((src, i) => (
                <a
                  key={i}
                  href={src.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="block p-2.5 rounded-lg bg-(--surface-2) border border-(--border) hover:border-(--accent)/30 transition-colors group"
                >
                  <div className="flex items-start gap-2">
                    <ExternalLink className="w-3 h-3 text-(--ink-faint) mt-0.5 shrink-0 group-hover:text-(--accent) transition-colors" />
                    <div className="min-w-0">
                      <div className="text-[12px] text-(--ink) font-medium truncate group-hover:text-(--accent) transition-colors">
                        {src.title}
                      </div>
                      {src.snippet && (
                        <div className="text-[11px] text-(--ink-muted) line-clamp-2 mt-0.5">
                          {src.snippet}
                        </div>
                      )}
                      <div className="text-[10px] text-(--ink-faint) mt-1 truncate">
                        {src.url.replace(/^https?:\/\//, '').replace(/\/$/, '')}
                      </div>
                    </div>
                  </div>
                </a>
              ))}
            </div>
          </div>
        )}
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
