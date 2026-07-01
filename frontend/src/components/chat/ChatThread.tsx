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
import { Globe } from 'lucide-react'
import { MarkdownContent } from './MarkdownContent'
import { ThinkingPane } from './ThinkingPane'

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
  const [pendingUserText, setPendingUserText] = useState<string | null>(null)
  const [chatLoading, setChatLoading] = useState(!!chatId)
  const [webSearchEnabled, setWebSearchEnabled] = useState(false)
  const [workersEnabled, setWorkersEnabled] = useState(true)
  const [thinkingEnabled, setThinkingEnabled] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)

  // Pending assistant message for streaming (desktop mode)
  const [pendingMessageId, setPendingMessageId] = useState<string | null>(null)
  const [pendingText, setPendingText] = useState<string>('')
  // Ephemeral reasoning trace (not persisted)
  const [pendingThinking, setPendingThinking] = useState<string>('')
  const [thinkingExpanded, setThinkingExpanded] = useState(true)
  const hasContentTokenRef = useRef(false)
  // Tool execution state for pending messages
  const [toolStatuses, setToolStatuses] = useState<Map<string, { name: string; status: string; summary: string }>>(new Map())
  const [sources, setSources] = useState<Map<string, Array<{ title: string; url: string; snippet: string }>>>(new Map())

  useEffect(() => {
    if (!chatId) { setChat(null); setChatLoading(false); return }
    setChatLoading(true)
    getChat(chatId)
      .then(data => { setChat(data); setChatLoading(false) })
      .catch(() => { setChat(null); setChatLoading(false) })
  }, [chatId])

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [chat?.messages.length, pendingText, pendingThinking])

  // Handle agent events for streaming
  const handleAgentEvent = useCallback((event: {
    chat_id: string
    message_id: string
    type: string
    payload: Record<string, unknown>
  }) => {
    if (event.chat_id !== chatId) return

    if (event.type === 'thinking_delta') {
      const text = typeof event.payload.text === 'string' ? event.payload.text : ''
      if (text) {
        setPendingMessageId(prev => prev ?? (event.message_id || 'pending-assistant'))
        setPendingThinking(prev => prev + text)
      }
    } else if (event.type === 'token') {
      const text = event.payload.text as string
      if (text) {
        setPendingMessageId(prev => prev ?? (event.message_id || 'pending-assistant'))
        setPendingText(prev => prev + text)
        // Auto-collapse the thinking pane once when the answer begins streaming.
        if (!hasContentTokenRef.current) {
          hasContentTokenRef.current = true
          setThinkingExpanded(false)
        }
      }
    } else if (event.type === 'done') {
      // Collect sources before resetting
      if (pendingMessageId && sources.has(pendingMessageId)) {
        setChat(prev => prev ? {
          ...prev,
          messages: prev.messages.map(m =>
            m.id === pendingMessageId
              ? { ...m, sources: sources.get(pendingMessageId) }
              : m,
          ),
        } : prev)
      }
      setPendingMessageId(null)
      setPendingText('')
      setPendingThinking('')
      setThinkingExpanded(false)
      hasContentTokenRef.current = false
      setToolStatuses(new Map())
      if (chatId) {
        getChat(chatId).then(setChat).catch(() => {})
      }
    } else if (event.type === 'error') {
      const msg = (event.payload.message as string) || 'An error occurred'
      setPendingMessageId(null)
      setPendingText('')
      setPendingThinking('')
      setThinkingExpanded(false)
      hasContentTokenRef.current = false
      setToolStatuses(new Map())
      addToast(msg, 'error', 4000)
    } else if (event.type === 'tool_progress') {
      const payload = event.payload as Record<string, unknown>
      const toolName = payload.tool_name as string
      const status = payload.status as string
      const summary = payload.summary as string
      const messageId = event.message_id || pendingMessageId
      if (messageId) {
        setToolStatuses(prev => {
          const next = new Map(prev)
          next.set(toolName, { name: toolName, status, summary })
          return next
        })
      }
    } else if (event.type === 'tool_result') {
      const payload = event.payload as Record<string, unknown>
      const resultStr = payload.result as string
      const messageId = event.message_id || pendingMessageId
      if (messageId && resultStr) {
        try {
          const result = JSON.parse(resultStr)
          if (result.results && Array.isArray(result.results)) {
            setSources(prev => {
              const next = new Map(prev)
              const existing = next.get(messageId) || []
              const newSources = result.results.filter((r: any) => r.url && r.title)
              next.set(messageId, [...existing, ...newSources])
              return next
            })
          }
        } catch {
          // Not JSON — ignore
        }
      }
    }
  }, [chatId, addToast, pendingMessageId, sources])

  useAgentEvent(handleAgentEvent)

  const handleSend = async (text: string, files: File[]) => {
    if (!text.trim() && files.length === 0) return
    setSending(true)
    if (!chatId) setPendingUserText(text)
    setPendingMessageId(null)
    setPendingText('')
    setPendingThinking('')
    setThinkingExpanded(true)
    hasContentTokenRef.current = false

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
        web_search: webSearchEnabled,
        workers_enabled: workersEnabled,
        thinking_enabled: thinkingEnabled,
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
      setPendingUserText(null)
    }
  }

  const ThinkingDots = (
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
  )

  if (!chatId || !chat) {
    // Remounting with a chatId but data not yet loaded — skeleton prevents EmptyState flash
    if (chatId && chatLoading) {
      return (
        <main className="flex-1 flex flex-col min-w-0">
          <header className="h-12 border-b border-(--border) px-6 flex items-center">
            <div className="h-4 w-48 bg-(--border) rounded animate-pulse" />
          </header>
          <div className="flex-1" />
        </main>
      )
    }

    // First message in flight — show user bubble + thinking dots instead of blank EmptyState
    if (!chatId && sending && pendingUserText !== null) {
      return (
        <main className="flex-1 flex flex-col min-w-0">
          <div ref={scrollRef} className="flex-1 overflow-y-auto px-6 py-8">
            <div className="max-w-[760px] mx-auto space-y-8">
              <div className="flex justify-end">
                <div className="max-w-[640px] text-[14px] text-(--ink) leading-relaxed whitespace-pre-wrap">
                  {pendingUserText}
                </div>
              </div>
              {ThinkingDots}
            </div>
          </div>
          <div className="border-t border-(--border) px-6 py-4">
            <div className="max-w-[760px] mx-auto">
              <Composer onSend={handleSend} disabled={true} webSearchEnabled={webSearchEnabled} onWebSearchChange={setWebSearchEnabled} thinkingEnabled={thinkingEnabled} onThinkingChange={setThinkingEnabled} />
            </div>
          </div>
        </main>
      )
    }

    return (
      <main className="flex-1 flex flex-col min-w-0">
        <EmptyState
            onChip={p => handleSend(p, [])}
            composer={<Composer onSend={handleSend} disabled={sending} webSearchEnabled={webSearchEnabled} onWebSearchChange={setWebSearchEnabled} thinkingEnabled={thinkingEnabled} onThinkingChange={setThinkingEnabled} />}
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
            <div className="flex gap-3">
              <img
                src={resolvedTheme === 'dark' ? ObrennaMonoWhite : ObrennaMono}
                alt="Obrenna"
                className="w-5 h-5 object-contain shrink-0 mt-0.5"
              />
              <div className="min-w-0 flex-1">
                <ThinkingPane
                  text={pendingThinking}
                  expanded={thinkingExpanded}
                  onExpandedChange={setThinkingExpanded}
                />
                <div className="text-[14px] text-(--ink)">
                  {pendingText
                    ? <MarkdownContent>{pendingText}</MarkdownContent>
                    : <span className="text-(--ink-muted)">...</span>}
                </div>
                {/* Tool progress indicators */}
                {Array.from(toolStatuses.entries())
                  .filter(([, ts]) => ts.status === 'running' || ts.status === 'pending')
                  .map(([name, ts]) => (
                    <div key={name} className="mt-1 flex items-center gap-1.5 text-[12px] text-(--ink-muted)">
                      <Globe className="w-3 h-3" />
                      <span>{ts.status === 'running' ? 'Searching...' : 'Preparing search...'}</span>
                    </div>
                  ))}
              </div>
            </div>
          )}
          {/* Thinking indicator while waiting for non-streaming LLM response */}
          {sending && !pendingMessageId && ThinkingDots}
        </div>
      </div>
      <div className="border-t border-(--border) px-6 py-4">
        <div className="max-w-[760px] mx-auto">
          <Composer onSend={handleSend} disabled={sending} webSearchEnabled={webSearchEnabled} onWebSearchChange={setWebSearchEnabled} thinkingEnabled={thinkingEnabled} onThinkingChange={setThinkingEnabled} />
        </div>
      </div>
    </main>
  )
}
