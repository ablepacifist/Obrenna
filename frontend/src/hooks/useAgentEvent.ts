import { useEffect, useRef } from 'react'

interface AgentEvent {
  channel: string
  chat_id: string
  message_id: string
  type: 'token' | 'done' | 'error' | 'tool_call' | 'tool_result' | 'tool_progress'
  payload: Record<string, unknown>
}

type EventCallback = (event: AgentEvent) => void

/**
 * Subscribe to Tauri agent-event stream for desktop mode.
 * Safe to use in browser — Tauri APIs are only loaded on desktop.
 */
export function useAgentEvent(callback: EventCallback): void {
  const callbackRef = useRef(callback)
  callbackRef.current = callback

  useEffect(() => {
    let cancelled = false

    // Only listen for events when running in a Tauri desktop environment.
    if (typeof window === 'undefined' || !(window as any).__TAURI__) return

    ;(async () => {
      try {
        const { listen } = await import('@tauri-apps/api/event')

        const unsubPromise = listen('agent-event', (raw: { payload: AgentEvent | string }) => {
          if (cancelled) return
          let event: AgentEvent
          if (typeof raw.payload === 'string') {
            try {
              event = JSON.parse(raw.payload)
            } catch {
              return
            }
          } else {
            event = raw.payload as AgentEvent
          }
          callbackRef.current(event)
        })

        return () => {
          cancelled = true
          unsubPromise.then(f => f()).catch(() => {})
        }
      } catch {
        // Tauri APIs unavailable — no-op in browser
      }
    })()

    return () => {
      cancelled = true
    }
  }, [])
}
