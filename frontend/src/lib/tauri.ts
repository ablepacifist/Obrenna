/** Tauri commands exposed to the frontend. */

let tauriApi: typeof import('@tauri-apps/api/core') | null = null

export function isDesktop(): boolean {
  return typeof window !== 'undefined' && !!(window as any).__TAURI__
}

async function ensureTauri() {
  if (!tauriApi && typeof window !== 'undefined' && (window as any).__TAURI__) {
    tauriApi = await import('@tauri-apps/api/core')
  }
  return tauriApi
}

export async function getApiBaseUrl(): Promise<string> {
  const api = await ensureTauri()
  if (!api) return ''
  const info: { base_url: string } = await api.invoke('get_api_base_url')
  return info.base_url
}

export async function getDataDir(): Promise<string> {
  const api = await ensureTauri()
  if (!api) return ''
  return await api.invoke('get_data_dir')
}

export async function openDataDir(): Promise<void> {
  const api = await ensureTauri()
  if (!api) return
  await api.invoke('open_data_dir')
}

export async function getAppVersion(): Promise<string> {
  const api = await ensureTauri()
  if (!api) return '0.0.0'
  return await api.invoke('get_app_version')
}

export async function checkUpdate(): Promise<{
  current_version: string
  update_available: boolean
  latest_version: string | null
  description: string | null
}> {
  const api = await ensureTauri()
  if (!api) return { current_version: '0.0.0', update_available: false, latest_version: null, description: null }
  return await api.invoke('check_update')
}

export async function installUpdate(): Promise<void> {
  const api = await ensureTauri()
  if (!api) return
  await api.invoke('install_update')
}

export async function openLogsDir(): Promise<void> {
  const api = await ensureTauri()
  if (!api) return
  await api.invoke('open_logs_dir')
}

export async function getLogsDir(): Promise<string> {
  const api = await ensureTauri()
  if (!api) return ''
  return await api.invoke('get_logs_dir')
}

export interface OllamaStatus {
  status: 'running' | 'started' | 'not_found' | 'error'
  message: string
}

export async function startOllama(): Promise<OllamaStatus> {
  const api = await ensureTauri()
  if (!api) {
    return { status: 'error', message: 'Desktop mode required' }
  }
  return await api.invoke('start_ollama')
}
