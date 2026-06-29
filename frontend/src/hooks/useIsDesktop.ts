/** Detect if running inside Tauri desktop shell. */

export function useIsDesktop(): boolean {
  if (typeof window === 'undefined') return false
  return !!(window as any).__TAURI__
}
