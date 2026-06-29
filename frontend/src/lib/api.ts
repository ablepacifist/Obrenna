/** Typed fetch client for the GrebGlob backend. */

const BASE = import.meta.env.VITE_API_BASE_URL ?? ''

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    const msg = await res.text().catch(() => res.statusText)
    throw new Error(`${method} ${path} → ${res.status}: ${msg}`)
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
  models: { main_reasoner?: string; summarizer?: string; utility?: string }
}
export type TestConnectionResult = { ok: boolean; models: string[]; latency_ms?: number; error?: string }
export type AppSettings = {
  setup_complete: boolean
  setup_mode: 'managed' | 'byo'
  theme: 'light' | 'dark' | 'system'
  active_models: string[]
  managed_plan: Record<string, unknown>
}

export const getModelEndpoint = () => req<ModelEndpointConfig>('GET', '/api/settings/model-endpoint')
export const saveModelEndpoint = (cfg: ModelEndpointConfig) => req<ModelEndpointConfig>('POST', '/api/settings/model-endpoint', cfg)
export const testModelEndpoint = (cfg: ModelEndpointConfig) => req<TestConnectionResult>('POST', '/api/settings/model-endpoint/test', cfg)
export const getAppSettings = () => req<AppSettings>('GET', '/api/settings/app')
export const saveAppSettings = (s: AppSettings) => req<AppSettings>('POST', '/api/settings/app', s)

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

export type ConfirmPlanResponse = { confirmed: boolean; plan: ManagedPlan }

export const getManagedPlan = () => req<ManagedPlan>('GET', '/api/setup/managed-plan')
export const confirmManagedPlan = () => req<ConfirmPlanResponse>('POST', '/api/setup/managed-plan/confirm')

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
  const res = await fetch(`${BASE}/api/files/upload`, { method: 'POST', body: fd })
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

export const downloadPdfUrl = (id: string) => `${BASE}/api/artifacts/${id}/export/pdf/download`

// ── chat ──────────────────────────────────────────────────────────────────────
export type ChatMessageDTO = {
  id: string
  role: 'user' | 'assistant'
  text: string
  artifacts: string[]
  files: { name: string; size: number }[]
  created_at: string
}
export type ChatResponse = { chat_id: string; message: ChatMessageDTO }
export type ChatDTO = { id: string; title: string; folder_id?: string; created_at: string; updated_at: string }
export type ChatDetailDTO = ChatDTO & { messages: ChatMessageDTO[] }

export const sendMessage = (payload: { chat_id?: string; message: string; file_ids?: string[] }) =>
  req<ChatResponse>('POST', '/api/chat', payload)

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
