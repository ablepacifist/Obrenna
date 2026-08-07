import { useEffect, useRef, useState, useCallback } from 'react'
import type { AgentMode, ChatDetailDTO, ChatResponse, CodebaseProjectDTO, MessageBlock } from '../../lib/api'
import { answerQuestion, decideApproval, getChat, getCodebaseProjects, sendMessage, sendMessageStream, updateChat, uploadFile } from '../../lib/api'
import { ApprovalCard } from './ApprovalCard'
import { QuestionCard } from './QuestionCard'
import { useAgentEvent } from '../../hooks/useAgentEvent'
import { Composer } from './Composer'
import { EmptyState } from './EmptyState'
import { MessageBubble } from './MessageBubble'
import { useToast } from '../ui/Toast'
import { useTheme } from '../../theme/ThemeProvider'
import { useAnimationPreference } from '../../context/AnimationPreferenceContext'
import ObrennaMono from '../../assets/logos/ObrennaMono.png'
import ObrennaMonoWhite from '../../assets/logos/ObrennaMonoWhite.png'
import { MarkdownContent } from './MarkdownContent'
import { ThinkingPane } from './ThinkingPane'
import { ActivityStrip, type ActivityStep } from './ActivityStrip'
import { ToolCallCard } from './ToolCallCard'

interface ChatThreadProps {
  chatId: string | null
  onOpenArtifact: (id: string) => void
  onChatCreated?: (chatId: string) => void
}

type AssistantMessageStatus = 'pending' | 'working' | 'streaming' | 'complete' | 'error'

type PendingArtifactSkeleton = {
  artifactType: string
  title: string
  sections: Array<{ kind: string; status: string }>
}

function createClientId() {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID()
  return `client-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

export function ChatThread({ chatId, onOpenArtifact, onChatCreated }: ChatThreadProps) {
  const { addToast } = useToast()
  const { resolvedTheme } = useTheme()
  const { style } = useAnimationPreference()
  const [chat, setChat] = useState<ChatDetailDTO | null>(null)
  const [sending, setSending] = useState(false)
  const [pendingUserText, setPendingUserText] = useState<string | null>(null)
  const [chatLoading, setChatLoading] = useState(!!chatId)
  const [webSearchEnabled, setWebSearchEnabled] = useState(false)
  const [workersEnabled] = useState(true)
  const [thinkingEnabled, setThinkingEnabled] = useState(false)
  const [codebaseProjects, setCodebaseProjects] = useState<CodebaseProjectDTO[]>([])
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    getCodebaseProjects().then(setCodebaseProjects).catch(() => {})
  }, [])

  // Codebase chosen before the chat exists (first message in a new chat).
  // There's no chat row to PATCH yet, so the selection is held here and sent
  // with the first message, which creates the chat already attached to it.
  const [draftCodebaseProjectId, setDraftCodebaseProjectId] = useState<string | null>(null)

  const handleCodebaseProjectChange = useCallback((projectId: string | null) => {
    if (!chatId) {
      setDraftCodebaseProjectId(projectId)
      return
    }
    setChat(prev => (prev ? { ...prev, active_codebase_project_id: projectId ?? undefined } : prev))
    const patch = projectId ? { active_codebase_project_id: projectId } : { clear_codebase_project: true }
    updateChat(chatId, patch).catch(() => {})
  }, [chatId])

  // What the composer's picker should show: the saved value once the chat
  // exists, otherwise the not-yet-persisted draft.
  const selectedCodebaseProjectId = chatId
    ? (chat?.active_codebase_project_id ?? null)
    : draftCodebaseProjectId

  // Write policy — same draft-until-the-chat-exists pattern as the codebase.
  const [draftAgentMode, setDraftAgentMode] = useState<AgentMode>('auto')
  const selectedAgentMode: AgentMode = chatId
    ? (chat?.agent_mode ?? 'auto')
    : draftAgentMode

  const handleAgentModeChange = useCallback((mode: AgentMode) => {
    if (!chatId) {
      setDraftAgentMode(mode)
      return
    }
    setChat(prev => (prev ? { ...prev, agent_mode: mode } : prev))
    updateChat(chatId, { agent_mode: mode }).catch(() => {})
  }, [chatId])

  // Pending assistant message for streaming (desktop mode)
  const [pendingMessageId, setPendingMessageId] = useState<string | null>(null)
  const [pendingStatus, setPendingStatus] = useState<AssistantMessageStatus>('pending')
  const [pendingPhaseLabel, setPendingPhaseLabel] = useState('Starting')
  const [pendingText, setPendingText] = useState<string>('')
  // Ordered content blocks for the in-flight message: text runs + tool-call
  // cards interleaved (the cadence). Tokens append to the last text block (or
  // start a new one), tool_call pushes a tool card, tool_result marks it done.
  // Survives the done-transition via locallyRenderedRef; cleared on reload.
  const [pendingBlocks, setPendingBlocks] = useState<MessageBlock[]>([])
  // Ephemeral reasoning trace (not persisted)
  const [pendingThinking, setPendingThinking] = useState<string>('')
  const [thinkingExpanded, setThinkingExpanded] = useState(true)
  const hasContentTokenRef = useRef(false)
  // The assistant message id generated for the in-flight send. Stream events
  // carrying a different message_id belong to an earlier turn and are dropped,
  // so late tokens/done from a previous turn can never bleed into (or close)
  // the current bubble.
  const activeAssistantIdRef = useRef<string | null>(null)
  const [activitySteps, setActivitySteps] = useState<ActivityStep[]>([])
  const [pendingArtifacts, setPendingArtifacts] = useState<PendingArtifactSkeleton[]>([])
  const [sources, setSources] = useState<Map<string, Array<{ title: string; url: string; snippet: string }>>>(new Map())
  // In-memory block rendering for messages just completed in this session.
  // Keyed by assistant message id; the refetched flat `text` must not clobber
  // these until the chat is reloaded (Step 7 will persist blocks server-side).
  const locallyRenderedRef = useRef<Map<string, { blocks: MessageBlock[]; sources?: Array<{ title: string; url: string; snippet: string }> }>>(new Map())

  const handleAnswerQuestion = useCallback((questionId: string, answer: string) => {
    // Optimistically settle; the question_resolved event confirms.
    setPendingBlocks(prev => prev.map(b =>
      b.kind === 'question' && b.questionId === questionId ? { ...b, answer } : b,
    ))
    answerQuestion(questionId, answer).catch(err => {
      const msg = err instanceof Error ? err.message : 'Failed to send answer'
      addToast(`Could not send that answer: ${msg}`, 'error', 5000)
    })
  }, [addToast])

  const handleApprovalDecision = useCallback((approvalId: string, decision: 'approve' | 'reject') => {
    // Optimistically settle the card; the approval_resolved event confirms it.
    setPendingBlocks(prev => prev.map(b =>
      b.kind === 'approval' && b.approvalId === approvalId ? { ...b, decision } : b,
    ))
    decideApproval(approvalId, decision).catch(err => {
      // The turn moved on without us (timed out, or the backend restarted).
      // Reverting the card to undecided would be misleading — the approval is
      // dead either way — so just say why nothing happened.
      const msg = err instanceof Error ? err.message : 'Failed to submit decision'
      addToast(`Could not ${decision} that change: ${msg}`, 'error', 5000)
    })
  }, [addToast])

  useEffect(() => {
    if (!chatId) { setChat(null); setChatLoading(false); return }
    setChatLoading(true)
    getChat(chatId)
      .then(data => { setChat(data); setChatLoading(false) })
      .catch(() => { setChat(null); setChatLoading(false) })
  }, [chatId])

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [chat?.messages.length, pendingText, pendingBlocks.length, pendingThinking, activitySteps.length, pendingArtifacts.length])

  useEffect(() => {
    if (!activitySteps.length) return
    const timer = setTimeout(() => setActivitySteps([]), 1000)
    return () => clearTimeout(timer)
  }, [activitySteps])

  const upsertActivityStep = useCallback((step: ActivityStep) => {
    setActivitySteps(prev => {
      const idx = prev.findIndex(s => s.key === step.key)
      if (idx === -1) return [...prev, step]
      const next = [...prev]
      next[idx] = { ...next[idx], ...step }
      return next
    })
  }, [])

  const clearPendingAssistant = useCallback(() => {
    activeAssistantIdRef.current = null
    setPendingMessageId(null)
    setPendingStatus('complete')
    setPendingPhaseLabel('')
    setPendingText('')
    setPendingBlocks([])
    setPendingThinking('')
    setThinkingExpanded(false)
    hasContentTokenRef.current = false
    setActivitySteps([])
    setPendingArtifacts([])
  }, [])

  // Handle agent events for streaming
  const handleAgentEvent = useCallback((event: {
    chat_id: string
    message_id: string
    type: string
    payload: Record<string, unknown>
  }) => {
    if (event.chat_id !== chatId && !(chatId === null && sending)) return
    // Scope stream events to the active turn: if a send is in flight and the
    // event names a different assistant message, it is a stale event from a
    // previous turn — ignore it. Events without a message_id (e.g. errors)
    // pass through.
    if (
      activeAssistantIdRef.current &&
      event.message_id &&
      event.message_id !== activeAssistantIdRef.current
    ) return

    if (event.type === 'phase') {
      const phase = typeof event.payload.phase === 'string' ? event.payload.phase : 'phase'
      const label = typeof event.payload.label === 'string' ? event.payload.label : phase
      const detail = typeof event.payload.detail === 'string' ? event.payload.detail : undefined
      setPendingMessageId(prev => prev ?? (event.message_id || 'pending-assistant'))
      setPendingStatus('working')
      setPendingPhaseLabel(label)
      setActivitySteps(prev => prev.map(step =>
        step.status === 'running' && step.key.startsWith('phase:')
          ? { ...step, status: 'done' as const }
          : step,
      ))
      upsertActivityStep({ key: `phase:${phase}`, label, detail, status: 'running' })
    } else if (event.type === 'thinking_delta') {
      const text = typeof event.payload.text === 'string' ? event.payload.text : ''
      if (text) {
        setPendingMessageId(prev => prev ?? (event.message_id || 'pending-assistant'))
        setPendingStatus('working')
        setPendingThinking(prev => prev + text)
      }
    } else if (event.type === 'token') {
      const text = event.payload.text as string
      if (text) {
        setPendingMessageId(prev => prev ?? (event.message_id || 'pending-assistant'))
        setPendingStatus('streaming')
        setPendingText(prev => prev + text)
        // Append to the last block if it's text, else start a new text block —
        // so text after a tool call begins a fresh run (the interleaved cadence).
        setPendingBlocks(prev => {
          const last = prev[prev.length - 1]
          if (last && last.kind === 'text') {
            const next = [...prev]
            next[next.length - 1] = { kind: 'text', text: last.text + text }
            return next
          }
          return [...prev, { kind: 'text', text }]
        })
        if (!hasContentTokenRef.current) {
          hasContentTokenRef.current = true
          setThinkingExpanded(false)
        }
      }
    } else if (event.type === 'done') {
      const finishedId = pendingMessageId
      if (finishedId && sources.has(finishedId)) {
        setChat(prev => prev ? {
          ...prev,
          messages: prev.messages.map(m =>
            m.id === finishedId
              ? { ...m, sources: sources.get(finishedId) }
              : m,
          ),
        } : prev)
      }
      // Preserve the block-based cadence for the just-completed message within
      // this session: stash the blocks, inject a synthetic assistant message
      // carrying them, and skip overwriting that id when the refetch lands.
      // On reload the refetch/empty cache returns flat text (Step 7 not done).
      if (finishedId && pendingBlocks.length > 0) {
        locallyRenderedRef.current.set(finishedId, { blocks: pendingBlocks, sources: sources.get(finishedId) })
        const flatText = pendingBlocks
          .filter(b => b.kind === 'text')
          .map(b => (b as Extract<MessageBlock, { kind: 'text' }>).text)
          .join('')
          .trim()
        const synthetic = {
          id: finishedId,
          role: 'assistant' as const,
          text: flatText,
          artifacts: [] as string[],
          files: [] as { name: string; size: number }[],
          created_at: new Date().toISOString(),
          sources: sources.get(finishedId),
          blocks: pendingBlocks,
        }
        setChat(prev => prev ? {
          ...prev,
          messages: [
            ...prev.messages.filter(m => m.id !== finishedId),
            synthetic,
          ],
        } : prev)
      }
      clearPendingAssistant()
      if (chatId) {
        getChat(chatId).then(data => {
          setChat(prev => {
            const localKeys = locallyRenderedRef.current
            if (localKeys.size === 0 || !prev) return data
            const localById = new Map(prev.messages.map(m => [m.id, m] as const))
            const merged = data.messages.map(m => localKeys.has(m.id) ? (localById.get(m.id) ?? m) : m)
            return { ...data, messages: merged }
          })
        }).catch(() => {})
      }
    } else if (event.type === 'error') {
      const msg = (event.payload.message as string) || 'An error occurred'
      setPendingStatus('error')
      upsertActivityStep({ key: 'error', label: msg, status: 'error' })
      clearPendingAssistant()
      addToast(msg, 'error', 4000)
    } else if (event.type === 'tool_call') {
      // Push a tool-call card into the ordered block list. Keyed by call_id so
      // a later tool_result can flip it to done. ActivityStrip still gets the
      // transient progress hint (auto-clears); the card itself persists.
      const payload = event.payload as Record<string, unknown>
      const toolName = typeof payload.tool_name === 'string' ? payload.tool_name : 'tool'
      const callId = typeof payload.call_id === 'string' ? payload.call_id : ''
      const args = payload.arguments && typeof payload.arguments === 'object'
        ? payload.arguments as Record<string, unknown>
        : {}
      setPendingMessageId(prev => prev ?? (event.message_id || 'pending-assistant'))
      setPendingBlocks(prev => {
        if (callId && prev.some(b => b.kind === 'tool' && b.callId === callId)) {
          return prev.map(b => b.kind === 'tool' && b.callId === callId
            ? { ...b, toolName, args }
            : b)
        }
        return [...prev, { kind: 'tool', callId, toolName, args, status: 'running' }]
      })
    } else if (event.type === 'approval_request') {
      // The backend turn is now SUSPENDED on this. Push an approval block so
      // the card renders in the cadence; nothing resumes until the user acts.
      const payload = event.payload as Record<string, unknown>
      const approvalId = typeof payload.approval_id === 'string' ? payload.approval_id : ''
      const callId = typeof payload.call_id === 'string' ? payload.call_id : ''
      const toolName = typeof payload.tool_name === 'string' ? payload.tool_name : 'tool'
      const args = payload.arguments && typeof payload.arguments === 'object'
        ? payload.arguments as Record<string, unknown>
        : {}
      if (approvalId) {
        setPendingMessageId(prev => prev ?? (event.message_id || 'pending-assistant'))
        setPendingStatus('working')
        setPendingPhaseLabel('Waiting for your approval')
        setPendingBlocks(prev => (
          prev.some(b => b.kind === 'approval' && b.approvalId === approvalId)
            ? prev
            : [...prev, { kind: 'approval', approvalId, callId, toolName, args }]
        ))
      }
    } else if (event.type === 'approval_resolved') {
      // Settle the card. Also covers decisions this client didn't make (another
      // window, or a timeout), so the UI can't be left showing a live prompt
      // for an approval the backend already moved past.
      const payload = event.payload as Record<string, unknown>
      const approvalId = typeof payload.approval_id === 'string' ? payload.approval_id : ''
      const decision = typeof payload.decision === 'string' ? payload.decision : ''
      if (approvalId && decision) {
        setPendingBlocks(prev => prev.map(b =>
          b.kind === 'approval' && b.approvalId === approvalId
            ? { ...b, decision: decision as 'approve' | 'reject' | 'timeout' }
            : b,
        ))
      }
    } else if (event.type === 'question_request') {
      // The backend turn is SUSPENDED on this question until it's answered.
      const payload = event.payload as Record<string, unknown>
      const questionId = typeof payload.question_id === 'string' ? payload.question_id : ''
      const callId = typeof payload.call_id === 'string' ? payload.call_id : ''
      const question = typeof payload.question === 'string' ? payload.question : ''
      const options = Array.isArray(payload.options)
        ? (payload.options as unknown[]).filter((o): o is string => typeof o === 'string')
        : []
      if (questionId && question) {
        setPendingMessageId(prev => prev ?? (event.message_id || 'pending-assistant'))
        setPendingStatus('working')
        setPendingPhaseLabel('Waiting for your answer')
        setPendingBlocks(prev => (
          prev.some(b => b.kind === 'question' && b.questionId === questionId)
            ? prev
            : [...prev, { kind: 'question', questionId, callId, question, options }]
        ))
      }
    } else if (event.type === 'question_resolved') {
      // Settle the card, including when the answer came from elsewhere or the
      // wait timed out (empty answer), so it can't sit there looking live.
      const payload = event.payload as Record<string, unknown>
      const questionId = typeof payload.question_id === 'string' ? payload.question_id : ''
      const answer = typeof payload.answer === 'string' ? payload.answer : ''
      if (questionId) {
        setPendingBlocks(prev => prev.map(b =>
          b.kind === 'question' && b.questionId === questionId
            ? { ...b, answer: answer || '(no answer — continued with an assumption)' }
            : b,
        ))
      }
    } else if (event.type === 'tool_progress') {
      const payload = event.payload as Record<string, unknown>
      const toolName = typeof payload.tool_name === 'string' ? payload.tool_name : 'tool'
      const status = typeof payload.status === 'string' ? payload.status : 'running'
      const summary = typeof payload.summary === 'string' ? payload.summary : toolName
      const stage = typeof payload.stage === 'string' ? payload.stage : undefined
      const callId = typeof payload.call_id === 'string' ? payload.call_id : ''
      const progress = typeof payload.progress_pct === 'number' ? `${payload.progress_pct}%` : undefined
      const messageId = event.message_id || pendingMessageId
      // Helper-model narration (stage="narrating") carries a call_id and a
      // human-readable summary; attach it to the matching tool card so the
      // headline describes what the tool is doing. Aggregate/done progress
      // events have no call_id and feed only the transient ActivityStrip.
      if (stage === 'narrating' && callId && typeof summary === 'string') {
        setPendingBlocks(prev => prev.map(b =>
          b.kind === 'tool' && b.callId === callId
            ? { ...b, description: summary }
            : b,
        ))
      }
      if (messageId) {
        setPendingMessageId(prev => prev ?? messageId)
        upsertActivityStep({
          key: `tool:${toolName}`,
          label: summary || toolName,
          detail: progress || stage,
          status: status === 'done' ? 'done' : status === 'error' ? 'error' : 'running',
        })
      }
    } else if (event.type === 'artifact_plan') {
      const artifactType = typeof event.payload.artifact_type === 'string' ? event.payload.artifact_type : 'artifact'
      const title = typeof event.payload.title === 'string' ? event.payload.title : 'Preparing artifact'
      setPendingMessageId(prev => prev ?? (event.message_id || 'pending-assistant'))
      setPendingStatus('working')
      upsertActivityStep({ key: `artifact:${artifactType}:plan`, label: title, status: 'running' })
    } else if (event.type === 'artifact_skeleton') {
      const artifactType = typeof event.payload.artifact_type === 'string' ? event.payload.artifact_type : 'artifact'
      const title = typeof event.payload.title === 'string' ? event.payload.title : 'Preparing artifact'
      const sections = Array.isArray(event.payload.sections)
        ? event.payload.sections.filter((s): s is { kind: string; status: string } => {
            return typeof (s as any)?.kind === 'string' && typeof (s as any)?.status === 'string'
          })
        : []
      setPendingMessageId(prev => prev ?? (event.message_id || 'pending-assistant'))
      setPendingArtifacts(prev => {
        const idx = prev.findIndex(a => a.artifactType === artifactType)
        const nextArtifact = { artifactType, title, sections }
        if (idx === -1) return [...prev, nextArtifact]
        const next = [...prev]
        next[idx] = nextArtifact
        return next
      })
      upsertActivityStep({ key: `artifact:${artifactType}:skeleton`, label: title, status: 'running' })
    } else if (event.type === 'artifact_update') {
      const artifactType = typeof event.payload.artifact_type === 'string' ? event.payload.artifact_type : 'artifact'
      const section = typeof event.payload.section === 'string' ? event.payload.section : 'artifact'
      const status = typeof event.payload.status === 'string' ? event.payload.status : 'running'
      setPendingArtifacts(prev => prev.map(artifact => {
        if (artifact.artifactType !== artifactType) return artifact
        return {
          ...artifact,
          sections: artifact.sections.map(s =>
            s.kind === section ? { ...s, status } : s,
          ),
        }
      }))
      upsertActivityStep({
        key: `artifact:${artifactType}:${section}`,
        label: section.replace(/_/g, ' '),
        status: status === 'done' ? 'done' : status === 'error' ? 'error' : 'running',
      })
    } else if (event.type === 'tool_result') {
      const payload = event.payload as Record<string, unknown>
      const resultStr = payload.result as string
      const callId = typeof payload.call_id === 'string' ? payload.call_id : ''
      const messageId = event.message_id || pendingMessageId
      // Flip the matching tool card to done with a short result preview.
      if (callId) {
        setPendingBlocks(prev => prev.map(b =>
          b.kind === 'tool' && b.callId === callId
            ? { ...b, status: 'done', summary: (resultStr || '').slice(0, 140) }
            : b,
        ))
      }
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
  }, [chatId, sending, addToast, pendingMessageId, pendingBlocks, sources, clearPendingAssistant, upsertActivityStep])

  useAgentEvent(handleAgentEvent)

  const handleSend = async (text: string, files: File[]) => {
    if (!text.trim() && files.length === 0) return
    const assistantMessageId = createClientId()
    activeAssistantIdRef.current = assistantMessageId
    setSending(true)
    if (!chatId) setPendingUserText(text)
    setPendingMessageId(assistantMessageId)
    setPendingStatus('pending')
    setPendingPhaseLabel('Starting')
    setPendingText('')
    setPendingBlocks([])
    setPendingThinking('')
    setActivitySteps([{ key: 'phase:accepted', label: 'Starting', status: 'running' }])
    setPendingArtifacts([])
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
      const sendPayload = {
        chat_id: chatId ?? undefined,
        message: text,
        file_ids: uploadedIds,
        assistant_message_id: assistantMessageId,
        web_search: webSearchEnabled,
        workers_enabled: workersEnabled,
        thinking_enabled: thinkingEnabled,
        // Only meaningful on the create path; an existing chat's codebase is
        // already persisted server-side.
        ...(!chatId && draftCodebaseProjectId
          ? { active_codebase_project_id: draftCodebaseProjectId }
          : {}),
        ...(!chatId && draftAgentMode !== 'auto' ? { agent_mode: draftAgentMode } : {}),
      }
      // Desktop gets live progress via Tauri's stdout->IPC bridge
      // (useAgentEvent), so it keeps using the plain blocking request. A
      // browser tab has no such side channel — without HTTP-level
      // streaming it sees nothing until the whole turn completes, which
      // both looks frozen and risks a Cloudflare 524 on slow turns through
      // the tunnel. sendMessageStream() feeds the same handleAgentEvent
      // reducer live via SSE instead.
      const isTauri = typeof window !== 'undefined' && !!(window as any).__TAURI__
      const resp: ChatResponse = isTauri
        ? await sendMessage(sendPayload)
        : await sendMessageStream(sendPayload, handleAgentEvent)

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
      clearPendingAssistant()
    } catch (err) {
      // Roll back the optimistic user message on failure.
      setChat(prev => prev ? {
        ...prev,
        messages: prev.messages.filter(m => m.id !== optimisticId),
      } : prev)
      const message = err instanceof Error ? err.message : 'Failed to send message'
      addToast(message, 'error', 5000)
      clearPendingAssistant()
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

  const PendingAssistant = pendingMessageId ? (
    <div className="flex gap-3" data-status={pendingStatus}>
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
          {pendingBlocks.length > 0 ? (
            <div className="space-y-2">
              {pendingBlocks.map((b, i) =>
                b.kind === 'text' ? (
                  <MarkdownContent key={i} streaming={style === 'scramble'}>{b.text}</MarkdownContent>
                ) : b.kind === 'question' ? (
                  <QuestionCard
                    key={b.questionId}
                    questionId={b.questionId}
                    question={b.question}
                    options={b.options}
                    answer={b.answer}
                    onAnswer={handleAnswerQuestion}
                  />
                ) : b.kind === 'approval' ? (
                  <ApprovalCard
                    key={b.approvalId}
                    approval={{
                      approval_id: b.approvalId,
                      chat_id: chatId ?? '',
                      message_id: pendingMessageId ?? '',
                      tool_name: b.toolName,
                      call_id: b.callId,
                      arguments: b.args,
                      created_at: 0,
                    }}
                    onDecide={handleApprovalDecision}
                    settled={b.decision === 'timeout' ? 'reject' : b.decision}
                  />
                ) : (
                  <ToolCallCard key={i} block={b} />
                ),
              )}
            </div>
          ) : pendingText ? (
            <MarkdownContent streaming={style === 'scramble'}>{pendingText}</MarkdownContent>
          ) : (
            <span className="text-(--ink-muted)">{pendingPhaseLabel || 'Starting'}</span>
          )}
        </div>
        <ActivityStrip steps={activitySteps} />
        {pendingArtifacts.length > 0 && (
          <div className="mt-4 space-y-2.5">
            {pendingArtifacts.map(artifact => (
              <div key={artifact.artifactType} className="rounded-xl border border-(--border) bg-(--surface) p-3">
                <div className="text-[12px] font-medium text-(--ink)">{artifact.title}</div>
                <div className="mt-2 grid grid-cols-3 gap-2">
                  {(artifact.sections.length ? artifact.sections : [{ kind: 'section', status: 'loading' }]).slice(0, 3).map(section => (
                    <div key={section.kind} className="rounded-md bg-(--surface-2) border border-(--border) p-2">
                      <div className="h-2 rounded bg-(--border-strong) animate-pulse" />
                      <div className="mt-2 text-[10px] text-(--ink-faint) truncate">
                        {section.kind.replace(/_/g, ' ')}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  ) : null

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

    // First message in flight — show user bubble + assistant shell instead of blank EmptyState
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
              {PendingAssistant || ThinkingDots}
            </div>
          </div>
          <div className="border-t border-(--border) px-6 py-4">
            <div className="max-w-[760px] mx-auto">
              <Composer onSend={handleSend} disabled={true} webSearchEnabled={webSearchEnabled} onWebSearchChange={setWebSearchEnabled} thinkingEnabled={thinkingEnabled} onThinkingChange={setThinkingEnabled} codebaseProjects={codebaseProjects} activeCodebaseProjectId={selectedCodebaseProjectId} onCodebaseProjectChange={handleCodebaseProjectChange} agentMode={selectedAgentMode} onAgentModeChange={handleAgentModeChange} />
            </div>
          </div>
        </main>
      )
    }

    return (
      <main className="flex-1 flex flex-col min-w-0">
        <EmptyState
            onChip={p => handleSend(p, [])}
            composer={<Composer onSend={handleSend} disabled={sending} webSearchEnabled={webSearchEnabled} onWebSearchChange={setWebSearchEnabled} thinkingEnabled={thinkingEnabled} onThinkingChange={setThinkingEnabled} codebaseProjects={codebaseProjects} activeCodebaseProjectId={selectedCodebaseProjectId} onCodebaseProjectChange={handleCodebaseProjectChange} agentMode={selectedAgentMode} onAgentModeChange={handleAgentModeChange} />}
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
          {PendingAssistant}
          {/* Thinking indicator while waiting for non-streaming LLM response */}
          {sending && !pendingMessageId && ThinkingDots}
        </div>
      </div>
      <div className="border-t border-(--border) px-6 py-4">
        <div className="max-w-[760px] mx-auto">
          <Composer onSend={handleSend} disabled={sending} webSearchEnabled={webSearchEnabled} onWebSearchChange={setWebSearchEnabled} thinkingEnabled={thinkingEnabled} onThinkingChange={setThinkingEnabled} codebaseProjects={codebaseProjects} activeCodebaseProjectId={selectedCodebaseProjectId} onCodebaseProjectChange={handleCodebaseProjectChange} agentMode={selectedAgentMode} onAgentModeChange={handleAgentModeChange} />
        </div>
      </div>
    </main>
  )
}
