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

export type ChatMessageDTO = {
  id: string
  role: 'user' | 'assistant'
  text: string
  artifacts: string[]
  files: { name: string; size: number }[]
  created_at: string
  sources?: { title: string; url: string; snippet: string }[]
  // UI-only (not persisted by the backend yet). Present on the in-flight and
  // just-completed assistant message so the cadence renders after `done`.
  blocks?: MessageBlock[]
}
export type ChatResponse = { chat_id: string; message: ChatMessageDTO; memory_events?: MemoryEvent[] }
export type ChatDTO = { id: string; title: string; folder_id?: string; created_at: string; updated_at: string }
export type ChatDetailDTO = ChatDTO & { messages: ChatMessageDTO[] }

export type SendMessageRequest = {
  chat_id?: string
  message: string
  file_ids?: string[]
  assistant_message_id?: string
  web_search?: boolean
  workers_enabled?: boolean
  thinking_enabled?: boolean
}

export const sendMessage = (payload: SendMessageRequest) =>
   req<ChatResponse>('POST', '/api/chat', {
     ...payload,
     thinking_enabled: payload.thinking_enabled ?? false,
   })

export const listChats = () => req<ChatDTO[]>('GET', '/api/chats')
export const createChat = (title?: string, folder_id?: string) =>
  req<ChatDTO>('POST', '/api/chats', { title: title ?? 'New chat', folder_id })
export const getChat = (id: string) => req<ChatDetailDTO>('GET', `/api/chats/${id}`)
export const updateChat = (id: string, patch: { title?: string; folder_id?: string; unfile?: boolean }) =>
  req<ChatDTO>('PATCH', `/api/chats/${id}`, patch)
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
