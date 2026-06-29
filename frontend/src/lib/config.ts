/** Runtime configuration for Obrenna.

Resolves the API base URL at runtime:
- In Tauri: calls `get_api_base_url` command
- In browser dev: uses `VITE_API_BASE_URL` if set, otherwise same-origin
- In production web: same-origin
*/

interface AppConfig {
  apiUrl: string
  isDesktop: boolean
  isSetupRequired: boolean
}

let cachedConfig: AppConfig | null = null
let configPromise: Promise<AppConfig> | null = null

async function resolveApiUrl(): Promise<string> {
  const envUrl = import.meta.env.VITE_API_BASE_URL
  if (envUrl) return envUrl

  if (typeof window !== 'undefined' && (window as any).__TAURI__) {
    try {
      const { invoke } = await import('@tauri-apps/api/core')
      const info: { base_url: string } = await invoke('get_api_base_url')
      return info.base_url
    } catch {
      return ''
    }
  }

  return ''
}

export async function getConfig(): Promise<AppConfig> {
  if (cachedConfig) return cachedConfig
  if (configPromise) return configPromise

  configPromise = (async () => {
    const apiUrl = await resolveApiUrl()
    cachedConfig = {
      apiUrl,
      isDesktop: typeof window !== 'undefined' && !!(window as any).__TAURI__,
      isSetupRequired: true,
    }
    return cachedConfig
  })()

  return configPromise
}

export function invalidateConfig(): void {
  cachedConfig = null
  configPromise = null
}

export function setConfigOverride(config: AppConfig): void {
  cachedConfig = config
  configPromise = null
}
