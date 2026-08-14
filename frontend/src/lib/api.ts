/** Typed fetch client for the Obrenna backend. */

import { getConfig } from './config'

async function getBase(): Promise<string> {
  const config = await getConfig()
  return config.apiUrl
}

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const base = await getBase()
  const res = await fetch(`${base}${path}`, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    const msg = await res.text().catch(() => res.statusText)
    throw new Error(`${method} ${path} → ${res.status}: ${msg}`)
  }
  if (res.status === 204 || res.headers.get('content-length') === '0') {
    return undefined as unknown as T
  }
  return res.json() as Promise<T>
}

// ── health ────────────────────────────────────────────────────────────────────
export const getHealth = () => req<{ ok: boolean }>('GET', '/health')

// ── settings ─────────────────────────────────────────────────────────────────
export type ModelEndpointConfig = {
  provider: string
  base_url: string
  api_key: string
  models: { orchestrator?: string; summarizer?: string; utility?: string }
}
export type TestConnectionResult = { ok: boolean; models: string[]; latency_ms?: number; error?: string }
export type AppSettings = {
  setup_complete: boolean
  setup_mode: 'managed' | 'byo'
  theme: 'light' | 'dark' | 'system'
  active_models: string[]
  managed_plan: Record<string, unknown>
  workers_enabled: boolean
  // Catalog slug forcing the reasoning/orchestrator model; null = auto (hardware pick).
  orchestrator_override?: string | null
}

export const getModelEndpoint = () => req<ModelEndpointConfig>('GET', '/api/settings/model-endpoint')
export const saveModelEndpoint = (cfg: ModelEndpointConfig) => req<ModelEndpointConfig>('POST', '/api/settings/model-endpoint', cfg)
export const testModelEndpoint = (cfg: ModelEndpointConfig) => req<TestConnectionResult>('POST', '/api/settings/model-endpoint/test', cfg)
export const getAppSettings = () => req<AppSettings>('GET', '/api/settings/app')
export const updateAppSettings = (s: Partial<AppSettings>) => req<AppSettings>('POST', '/api/settings/app', s)
export const saveAppSettings = updateAppSettings

// ── system ────────────────────────────────────────────────────────────────────
export type GpuInfo = { name: string; vram_gb?: number }
export type HardwareInfo = {
  os: string
  cpu: string
  ram_gb?: number
  gpu: GpuInfo[]
  vram_gb?: number
  recommended_profile: 'local' | 'external_endpoint'
}
export const getHardware = () => req<HardwareInfo>('GET', '/api/system/hardware')

// ── models catalog ────────────────────────────────────────────────────────────
export type CatalogModel = {
  id: string
  name: string
  role: string
  size: string
  size_gb: number
  fit: 'ok' | 'warn' | 'bad'
  note: string
}
export const getModelCatalog = () => req<CatalogModel[]>('GET', '/api/models/catalog')

export type ModelRoleState = 'loaded' | 'installed' | 'missing'
export type ModelRoleStatus = {
  role: string
  label: string
  display_name: string
  available: boolean
  state: ModelRoleState
}
export type ModelStatus = {
  connected: boolean
  all_ready: boolean
  chat_ready: boolean
  roles: ModelRoleStatus[]
  error: string | null
}
export const getModelStatus = () => req<ModelStatus>('GET', '/api/models/status')

// ── managed setup plan -------------------------------------------------------
export type ModelRef = {
  model: string
  quant: string
  device: string
  ctx_min?: number
  ctx_max?: number
}

export type ManagedPlan = {
  path: 'apple' | 'gpu' | 'cpu_only' | 'reject'
  plan_id?: string
  plan_rank?: number
  ctx?: number
  helper_count: number
  fingerprint_hash: string
  runtime_priority: string[]
  runtime_forbidden: string[]
  required_launch_flags: string[]
  recommended_setup_mode: 'managed' | 'byo'
  action: string
  reason?: string | null
  detection_warnings: string[]
  orchestrator: ModelRef | null
  summarizer: ModelRef | null
  utility: ModelRef | null
  optional_orchestrator?: Record<string, unknown> | null
  validation_stubbed: boolean
}

export type ConfirmPlanResponse = {
  confirmed: boolean
  plan: ManagedPlan
  job_id: string
  status: string
  runtime_kind: string
  supports_pull: boolean
  supports_streaming_progress: boolean
  reused: boolean
}

export type ProvisioningItem = {
  id: string
  role: string
  model_slug: string
  quant: string
  status: string
  progress_pct: number
  bytes_downloaded: number
  bytes_total: number
  error_message?: string | null
  updated_at: string
}

export type ProvisioningJobSnapshot = {
  id: string
  fingerprint_hash: string
  runtime_kind: string
  status: string
  error_message?: string | null
  started_at: string
  completed_at?: string | null
  items: ProvisioningItem[]
}

export const getManagedPlan = () => req<ManagedPlan>('GET', '/api/setup/managed-plan')
export const confirmManagedPlan = () => req<ConfirmPlanResponse>('POST', '/api/setup/managed-plan/confirm')
export const getProvisioningJob = (jobId: string) => req<ProvisioningJobSnapshot>('GET', `/api/setup/provisioning/${jobId}`)
export const retryProvisioningJob = (jobId: string) => req<{ ok: boolean; job_id: string; status: string; retried: number }>('POST', `/api/setup/provisioning/${jobId}/retry`)
export async function getProvisioningEventsUrl(jobId: string, cursor = 0): Promise<string> {
  const base = await getBase()
  return `${base}/api/setup/provisioning/${jobId}/events?cursor=${cursor}`
}

// ── files ─────────────────────────────────────────────────────────────────────
export type FileDTO = {
  id: string
  filename: string
  content_type?: string
  size_bytes: number
  row_count?: number
  columns?: string[]
  created_at: string
}
export async function uploadFile(file: File): Promise<FileDTO> {
  const fd = new FormData()
  fd.append('file', file)
  const base = await getBase()
  const res = await fetch(`${base}/api/files/upload`, { method: 'POST', body: fd })
  if (!res.ok) throw new Error(`Upload failed: ${res.status}`)
  return res.json()
}

// ── artifacts ─────────────────────────────────────────────────────────────────
export type ArtifactResponse = { artifact_id: string; artifact: Record<string, unknown> }
export type ExportPdfResponse = { artifact_id: string; download_path: string; filename: string }

export const dashboardFromCsv = (file_id: string, instruction?: string) =>
  req<ArtifactResponse>('POST', '/api/artifacts/dashboard-from-csv', { file_id, instruction })

export const getArtifact = (id: string) => req<ArtifactResponse>('GET', `/api/artifacts/${id}`)

export const exportPdf = (id: string) =>
  req<ExportPdfResponse>('POST', `/api/artifacts/${id}/export/pdf`)

export async function downloadPdfUrl(id: string): Promise<string> {
  const base = await getBase()
  return `${base}/api/artifacts/${id}/export/pdf/download`
}

// ── chat ──────────────────────────────────────────────────────────────────────

// Ordered content blocks for an assistant message. The backend streams these
// as discrete events (token / tool_call / tool_result) so the UI can render an
// interleaved cadence — prose → tool card → prose → tool card — instead of one
// flat string. `blocks` is UI-only: the backend still persists flat `text`
// (Step 7 will persist blocks server-side); the frontend attaches blocks
// in-memory for the in-flight and just-completed message so the cadence
// survives the done-transition within a session, then falls back to flat text
// on reload.
export type MessageBlock =
  | { kind: 'text'; text: string }
  | {
      kind: 'tool'
      callId: string
      toolName: string
      args: Record<string, unknown>
      status: 'running' | 'done' | 'error'
      summary?: string
      description?: string
    }
  // A write awaiting your decision. Lives in the block list so it renders in
  // the right place in the cadence (after the prose that led up to it). While
  // `decision` is undefined the backend turn is genuinely suspended on it.
  | {
      kind: 'approval'
      approvalId: string
      callId: string
      toolName: string
      args: Record<string, unknown>
      decision?: 'approve' | 'reject' | 'timeout'
    }
  // An ask_user question. Same suspension semantics as an approval: while
  // `answer` is undefined the backend turn is blocked on it.
  | {
      kind: 'question'
      questionId: string
      callId: string
      question: string
      options: string[]
      answer?: string
    }

export type ChatMessageDTO = {
  id: string
  role: 'user' | 'assistant'
  text: string
  artifacts: string[]
  files: { name: string; size: number }[]
  created_at: string
  sources?: { title: string; url: string; snippet: string }[]
  // Ordered render blocks. Persisted server-side, so a reloaded transcript
  // replays the same cadence (including edit diffs) the user watched live.
  // Empty/absent on messages written before blocks were persisted — the UI
  // falls back to `text` for those.
  blocks?: MessageBlock[]
}
export type ChatResponse = { chat_id: string; message: ChatMessageDTO; memory_events?: MemoryEvent[] }

/** How much latitude the agent has over files in a chat.
 *  auto   — writes apply unattended
 *  manual — every write pauses the turn for your approval
 *  plan   — writes refused; the agent reads and proposes only */
export type AgentMode = 'auto' | 'manual' | 'plan'

export type ChatDTO = {
  id: string
  title: string
  folder_id?: string
  active_codebase_project_id?: string | null
  agent_mode?: AgentMode
  created_at: string
  updated_at: string
}
export type ChatDetailDTO = ChatDTO & { messages: ChatMessageDTO[] }

export type SendMessageRequest = {
  chat_id?: string
  message: string
  file_ids?: string[]
  assistant_message_id?: string
  web_search?: boolean
  workers_enabled?: boolean
  thinking_enabled?: boolean
  /** Codebase to attach when this send CREATES the chat (no chat_id yet).
   *  Existing chats change codebase via updateChat() instead. */
  active_codebase_project_id?: string
  /** Write policy for the chat this send creates. Same create-path-only
   *  reasoning as active_codebase_project_id. */
  agent_mode?: AgentMode
}

/** A write the agent wants to make, with the turn suspended until you decide.
 *  `arguments` carries the full tool args (old_string/new_string for an edit)
 *  so the diff can be rendered exactly as it will be applied. */
export type PendingApprovalDTO = {
  approval_id: string
  chat_id: string
  message_id: string
  tool_name: string
  call_id: string
  arguments: Record<string, unknown>
  created_at: number
}

/** Resolve a suspended write, resuming the turn. */
export const decideApproval = (approvalId: string, decision: 'approve' | 'reject') =>
  req<{ approval_id: string; decision: string; chat_id: string }>(
    'POST', `/api/chat/approvals/${approvalId}`, { decision },
  )

/** Approvals still blocking a chat's turn. Used to recover the approval card
 *  after a reload mid-turn, which would otherwise look like a hung turn. */
export const getChatApprovals = (chatId: string) =>
  req<PendingApprovalDTO[]>('GET', `/api/chat/approvals/${chatId}`)

/** A question the agent is suspended on, awaiting an answer. */
export type PendingQuestionDTO = {
  question_id: string
  chat_id: string
  message_id: string
  call_id: string
  question: string
  options: string[]
  created_at: number
}

/** Answer a suspended ask_user question, resuming the turn. */
export const answerQuestion = (questionId: string, answer: string) =>
  req<{ question_id: string; chat_id: string }>(
    'POST', `/api/chat/questions/${questionId}`, { answer },
  )

/** Questions still blocking a chat's turn (reload recovery, as above). */
export const getChatQuestions = (chatId: string) =>
  req<PendingQuestionDTO[]>('GET', `/api/chat/questions/${chatId}`)

export const sendMessage = (payload: SendMessageRequest) =>
   req<ChatResponse>('POST', '/api/chat', {
     ...payload,
     thinking_enabled: payload.thinking_enabled ?? false,
   })

// Shape of each live orchestrator event relayed over the stream — matches
// the backend's StreamEvent.to_envelope() and the Tauri-side AgentEvent type
// in hooks/useAgentEvent.ts, so the same reducer can consume either source.
export type AgentStreamEvent = {
  channel: string
  chat_id: string
  message_id: string
  type: string
  payload: Record<string, unknown>
}

// Browser-only counterpart to sendMessage(): consumes POST /api/chat/stream
// (Server-Sent Events) instead of waiting for one blocking JSON response.
// EventSource can't be used here — it's GET-only and this endpoint needs a
// POST body — so this reads the response body directly and parses SSE
// framing by hand. Every `data:` line is guaranteed single-line JSON (the
// backend always json.dumps onto one line), so no multi-line data: handling
// is needed; `:`-prefixed lines are heartbeat comments and are skipped.
export async function sendMessageStream(
  payload: SendMessageRequest,
  onEvent: (event: AgentStreamEvent) => void,
): Promise<ChatResponse> {
  const base = await getBase()
  const res = await fetch(`${base}/api/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...payload, thinking_enabled: payload.thinking_enabled ?? false }),
  })
  if (!res.ok || !res.body) {
    const msg = await res.text().catch(() => res.statusText)
    throw new Error(`POST /api/chat/stream → ${res.status}: ${msg}`)
  }

  const reader = res.body.getReader()
  // {stream: true} buffers any incomplete multi-byte UTF-8 sequence left at
  // a chunk boundary instead of mangling it — chat text is not ASCII-only.
  const decoder = new TextDecoder()
  let buffer = ''
  let result: ChatResponse | null = null
  let streamError: string | null = null

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    let sepIndex: number
    while ((sepIndex = buffer.indexOf('\n\n')) !== -1) {
      const block = buffer.slice(0, sepIndex)
      buffer = buffer.slice(sepIndex + 2)

      let eventName = 'message'
      let data: string | null = null
      for (const line of block.split('\n')) {
        if (line.startsWith(':')) continue
        if (line.startsWith('event:')) eventName = line.slice(6).trim()
        else if (line.startsWith('data:')) data = line.slice(5).trim()
      }
      if (data === null) continue

      if (eventName === 'agent_event') {
        try { onEvent(JSON.parse(data)) } catch { /* malformed frame — ignore */ }
      } else if (eventName === 'response') {
        result = JSON.parse(data) as ChatResponse
      } else if (eventName === 'error') {
        const parsed = JSON.parse(data) as { message?: string }
        streamError = parsed.message || 'Chat stream failed'
      }
    }
  }

  if (streamError) throw new Error(streamError)
  if (!result) throw new Error('Chat stream ended without a response')
  return result
}

export const listChats = () => req<ChatDTO[]>('GET', '/api/chats')
export const createChat = (title?: string, folder_id?: string) =>
  req<ChatDTO>('POST', '/api/chats', { title: title ?? 'New chat', folder_id })
export const getChat = (id: string) => req<ChatDetailDTO>('GET', `/api/chats/${id}`)
export const updateChat = (
  id: string,
  patch: {
    title?: string
    folder_id?: string
    unfile?: boolean
    active_codebase_project_id?: string
    clear_codebase_project?: boolean
  },
) => req<ChatDTO>('PATCH', `/api/chats/${id}`, patch)
export const deleteChat = (id: string) => req<void>('DELETE', `/api/chats/${id}`)

// ── folders ───────────────────────────────────────────────────────────────────
export type FolderDTO = { id: string; name: string; created_at: string }

export const listFolders = () => req<FolderDTO[]>('GET', '/api/folders')
export const createFolder = (name?: string) => req<FolderDTO>('POST', '/api/folders', { name: name ?? 'New folder' })
export const renameFolder = (id: string, name: string) => req<FolderDTO>('PATCH', `/api/folders/${id}`, { name })
export const deleteFolder = (id: string) => req<void>('DELETE', `/api/folders/${id}`)

// ── memory ────────────────────────────────────────────────────────────────────
export type MemoryFactDTO = {
  id: string
  fact_text: string
  source_chat_id?: string | null
  user_locked: boolean
  created_at: string
  updated_at: string
}

export type MemoryEvent = {
  type: string
  fact_id?: string
  text?: string
  count?: number
}

export const getMemoryFacts = () => req<MemoryFactDTO[]>('GET', '/api/memory/facts')
export const createMemoryFact = (fact_text: string) =>
  req<MemoryFactDTO>('POST', '/api/memory/facts', { fact_text })
export const updateMemoryFact = (id: string, fact_text: string) =>
  req<MemoryFactDTO>('PATCH', `/api/memory/facts/${id}`, { fact_text })
export const deleteMemoryFact = (id: string) =>
  req<{ deleted: boolean; fact_id: string }>('DELETE', `/api/memory/facts/${id}`)

// ── custom tools ─────────────────────────────────────────────────────────────
export type CustomToolParamDTO = {
  name: string
  description: string
  required: boolean
  location: 'query' | 'body'
  type: 'string' | 'number' | 'boolean'
}

export type CustomToolDTO = {
  id: string
  name: string
  description: string
  base_url: string
  http_method: string
  headers: Record<string, string>
  params: CustomToolParamDTO[]
  enabled: boolean
  created_at: string
  updated_at: string
}

export type CustomToolInput = {
  name: string
  description: string
  base_url: string
  http_method: string
  headers: Record<string, string>
  params: CustomToolParamDTO[]
  enabled?: boolean
}

export const getCustomTools = () => req<CustomToolDTO[]>('GET', '/api/custom-tools')
export const createCustomTool = (input: CustomToolInput) =>
  req<CustomToolDTO>('POST', '/api/custom-tools', input)
export const updateCustomTool = (id: string, input: Partial<CustomToolInput>) =>
  req<CustomToolDTO>('PATCH', `/api/custom-tools/${id}`, input)
export const deleteCustomTool = (id: string) =>
  req<{ deleted: boolean; tool_id: string }>('DELETE', `/api/custom-tools/${id}`)

// ── codebase agent devices ──────────────────────────────────────────────────
export type CodebaseAgentDeviceDTO = {
  id: string
  device_id: string
  name: string
  approved: boolean
  enabled: boolean
  connected: boolean
  created_at: string
  last_seen_at: string
}

export const getCodebaseAgentDevices = () => req<CodebaseAgentDeviceDTO[]>('GET', '/api/codebase-agent-devices')
export const approveCodebaseAgentDevice = (id: string) =>
  req<CodebaseAgentDeviceDTO>('POST', `/api/codebase-agent-devices/${id}/approve`)
export const deleteCodebaseAgentDevice = (id: string) =>
  req<{ deleted: boolean; device_row_id: string }>('DELETE', `/api/codebase-agent-devices/${id}`)

// ── codebase projects ────────────────────────────────────────────────────────
export type CodebaseProjectDTO = {
  id: string
  name: string
  device_id: string
  root_path: string
  write_enabled: boolean
  enabled: boolean
  created_at: string
  updated_at: string
}

export type CodebaseProjectInput = {
  name: string
  device_id: string
  root_path: string
  write_enabled?: boolean
}

export const getCodebaseProjects = () => req<CodebaseProjectDTO[]>('GET', '/api/codebase-projects')
export const createCodebaseProject = (input: CodebaseProjectInput) =>
  req<CodebaseProjectDTO>('POST', '/api/codebase-projects', input)
export const updateCodebaseProject = (
  id: string,
  input: Partial<Pick<CodebaseProjectDTO, 'name' | 'write_enabled' | 'enabled'>>,
) => req<CodebaseProjectDTO>('PATCH', `/api/codebase-projects/${id}`, input)
export const deleteCodebaseProject = (id: string) =>
  req<{ deleted: boolean; project_id: string }>('DELETE', `/api/codebase-projects/${id}`)
