import { useEffect, useRef, useState } from 'react'
import type { ChatDetailDTO, ChatResponse } from '../../lib/api'
import { getChat, sendMessage, uploadFile } from '../../lib/api'
import { Composer } from './Composer'
import { EmptyState } from './EmptyState'
import { MessageBubble } from './MessageBubble'
import { useToast } from '../ui/Toast'

interface ChatThreadProps {
  chatId: string | null
  onOpenArtifact: (id: string) => void
}

export function ChatThread({ chatId, onOpenArtifact }: ChatThreadProps) {
  const { addToast } = useToast()
  const [chat, setChat] = useState<ChatDetailDTO | null>(null)
  const [sending, setSending] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!chatId) { setChat(null); return }
    getChat(chatId).then(setChat).catch(() => setChat(null))
  }, [chatId])

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [chat?.messages.length])

  const handleSend = async (text: string, files: File[]) => {
    if (!text.trim() && files.length === 0) return
    setSending(true)
    try {
      const uploadedIds: string[] = []
      for (const f of files) {
        const dto = await uploadFile(f)
        uploadedIds.push(dto.id)
      }
      const resp: ChatResponse = await sendMessage({
        chat_id: chatId ?? undefined,
        message: text,
        file_ids: uploadedIds,
      })
      // Show memory toast for relevant events
      if (resp.memory_events && resp.memory_events.length > 0) {
        for (const ev of resp.memory_events) {
          if (ev.type === 'MEMORY_ACTIVE') {
            addToast(`Added to memory (${ev.count} memories)`, 'success', 2500)
          }
        }
      }
      // Reload chat to get fresh messages including the new assistant reply.
      const updated = await getChat(resp.chat_id)
      setChat(updated)
    } catch {
      // TODO: show error toast
    } finally {
      setSending(false)
    }
  }

  if (!chatId || !chat) {
    return (
      <main className="flex-1 flex flex-col min-w-0">
        <EmptyState
          onChip={p => handleSend(p, [])}
          composer={<Composer onSend={handleSend} disabled={sending} />}
        />
      </main>
    )
  }

  return (
    <main className="flex-1 flex flex-col min-w-0">
      <header className="h-12 border-b border-(--border) px-6 flex items-center">
        <div className="min-w-0">
          <div className="text-[14px] font-medium text-(--ink) truncate">{chat.title}</div>
          {chat.folder_id && (
            <div className="text-[11px] text-(--ink-faint)">In a folder</div>
          )}
        </div>
      </header>
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-6 py-8">
        <div className="max-w-[760px] mx-auto space-y-8">
          {chat.messages.map((m, i) => (
            <MessageBubble
              key={m.id}
              msg={m}
              onOpenArtifact={onOpenArtifact}
              isLatestAssistant={i === chat.messages.length - 1 && m.role === 'assistant'}
            />
          ))}
        </div>
      </div>
      <div className="border-t border-(--border) px-6 py-4">
        <div className="max-w-[760px] mx-auto">
          <Composer onSend={handleSend} disabled={sending} />
        </div>
      </div>
    </main>
  )
}
