import { useEffect, useRef, useState, useCallback } from 'react'
import type { ChatDetailDTO, ChatResponse } from '../../lib/api'
import { getChat, sendMessage, uploadFile } from '../../lib/api'
import { useAgentEvent } from '../../hooks/useAgentEvent'
import { Composer } from './Composer'
import { EmptyState } from './EmptyState'
import { MessageBubble } from './MessageBubble'
import { useToast } from '../ui/Toast'
import { useTheme } from '../../theme/ThemeProvider'
import ObrennaMono from '../../assets/logos/ObrennaMono.png'
import ObrennaMonoWhite from '../../assets/logos/ObrennaMonoWhite.png'

interface ChatThreadProps {
  chatId: string | null
  onOpenArtifact: (id: string) => void
  onChatCreated?: (chatId: string) => void
}

export function ChatThread({ chatId, onOpenArtifact, onChatCreated }: ChatThreadProps) {
  const { addToast } = useToast()
  const { resolvedTheme } = useTheme()
  const [chat, setChat] = useState<ChatDetailDTO | null>(null)
  const [sending, setSending] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)

  // Pending assistant message for streaming (desktop mode)
  const [pendingMessageId, setPendingMessageId] = useState<string | null>(null)
  const [pendingText, setPendingText] = useState<string>('')

  useEffect(() => {
    if (!chatId) { setChat(null); return }
    getChat(chatId).then(setChat).catch(() => setChat(null))
  }, [chatId])

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [chat?.messages.length, pendingText])

  // Handle agent events for streaming
  const handleAgentEvent = useCallback((event: {
    chat_id: string
    message_id: string
    type: string
    payload: Record<string, unknown>
  }) => {
    if (event.chat_id !== chatId) return

    if (event.type === 'token') {
      const text = event.payload.text as string
      if (text) {
        setPendingText(prev => prev + text)
      }
    } else if (event.type === 'done') {
      setPendingMessageId(null)
      setPendingText('')
      // Reload chat to get the finalized message
      if (chatId) {
        getChat(chatId).then(setChat).catch(() => {})
      }
    } else if (event.type === 'error') {
      const msg = (event.payload.message as string) || 'An error occurred'
      setPendingMessageId(null)
      setPendingText('')
      addToast(msg, 'error', 4000)
    }
  }, [chatId, addToast])

  useAgentEvent(handleAgentEvent)

  const handleSend = async (text: string, files: File[]) => {
    if (!text.trim() && files.length === 0) return
    setSending(true)
    setPendingMessageId(null)
    setPendingText('')

    // Optimistically append the user message to the visible thread immediately
    // (only when we're already in a chat thread, not the empty-state flow).
    const optimisticId = `optimistic-${Date.now()}`
    if (chatId && chat) {
      setChat(prev => prev ? {
        ...prev,
        messages: [...prev.messages, {
          id: optimisticId,
          role: 'user',
          text,
          artifacts: [],
          files: files.map(f => ({ name: f.name, size: f.size })),
          created_at: new Date().toISOString(),
        }],
      } : prev)
    }

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

      if (!chatId) {
        // First message in a new chat — notify App so it sets activeChatId and
        // refreshes the sidebar. The ChatThread will remount with the real chatId
        // and fetch its messages from scratch.
        onChatCreated?.(resp.chat_id)
      } else {
        // Existing chat — replace optimistic messages with the real server state.
        const updated = await getChat(resp.chat_id)
        setChat(updated)
      }
    } catch (err) {
      // Roll back the optimistic user message on failure.
      setChat(prev => prev ? {
        ...prev,
        messages: prev.messages.filter(m => m.id !== optimisticId),
      } : prev)
      const message = err instanceof Error ? err.message : 'Failed to send message'
      addToast(message, 'error', 5000)
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
          {/* Pending streaming message (desktop mode) */}
          {pendingMessageId && (
            <MessageBubble
              msg={{
                id: pendingMessageId,
                role: 'assistant',
                text: pendingText || '...',
                artifacts: [],
                files: [],
                created_at: new Date().toISOString(),
              }}
              onOpenArtifact={onOpenArtifact}
              isLatestAssistant={true}
            />
          )}
          {/* Thinking indicator while waiting for non-streaming LLM response */}
          {sending && !pendingMessageId && (
            <div className="flex gap-3">
              <img
                src={resolvedTheme === 'dark' ? ObrennaMonoWhite : ObrennaMono}
                alt="Obrenna"
                className="w-5 h-5 object-contain shrink-0 mt-0.5"
              />
              <div className="flex items-center gap-1 px-3 py-2 rounded-xl bg-(--surface) border border-(--border) text-(--ink-muted)">
                <span className="w-1.5 h-1.5 rounded-full bg-(--ink-muted) animate-bounce [animation-delay:0ms]" />
                <span className="w-1.5 h-1.5 rounded-full bg-(--ink-muted) animate-bounce [animation-delay:150ms]" />
                <span className="w-1.5 h-1.5 rounded-full bg-(--ink-muted) animate-bounce [animation-delay:300ms]" />
              </div>
            </div>
          )}
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
