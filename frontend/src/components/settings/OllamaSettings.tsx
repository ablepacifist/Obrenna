import { useEffect, useState } from 'react'
import { startOllama, isDesktop } from '../../lib/tauri'

interface OllamaStatusResult {
  status: 'running' | 'started' | 'not_found' | 'error'
  message: string
}

export function OllamaSettings() {
  const [status, setStatus] = useState<OllamaStatusResult | null>(null)
  const [checking, setChecking] = useState(true)
  const [starting, setStarting] = useState(false)

  const checkStatus = async () => {
    setChecking(true)
    try {
      const result = await startOllama()
      setStatus(result)
    } catch {
      setStatus(null)
    } finally {
      setChecking(false)
    }
  }

  useEffect(() => {
    checkStatus()
  }, [])

  const handleStart = async () => {
    setStarting(true)
    try {
      const result = await startOllama()
      setStatus(result)
      if (result.status === 'started' || result.status === 'running') {
        setTimeout(() => checkStatus(), 3000)
      }
    } catch {
      setStatus({ status: 'error', message: 'Failed to start Ollama.' })
    } finally {
      setStarting(false)
    }
  }

  if (!isDesktop()) {
    return (
      <div>
        <h3 className="text-[18px] font-semibold tracking-tight text-(--ink)">Ollama</h3>
        <p className="mt-1 text-[13px] text-(--ink-muted) leading-relaxed">
          Ollama controls are only available in the desktop app.
        </p>
      </div>
    )
  }

  return (
    <div>
      <h3 className="text-[18px] font-semibold tracking-tight text-(--ink)">Ollama</h3>
      <p className="mt-1 text-[13px] text-(--ink-muted) leading-relaxed">
        The local Ollama engine is bundled with Obrenna and starts automatically. Use this if it ever
        stops — no separate install required.
      </p>

      <div className="mt-5 rounded-xl border border-(--border) bg-(--surface) p-4">
        {checking ? (
          <div className="text-[13px] text-(--ink-muted)">Checking Ollama status…</div>
        ) : status ? (
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <span className={`inline-block w-2 h-2 rounded-full ${
                status.status === 'running' || status.status === 'started'
                  ? 'bg-(--ok)'
                  : status.status === 'not_found'
                    ? 'bg-(--ink-muted)'
                    : 'bg-(--err)'
              }`} />
              <span className="text-[14px] font-medium text-(--ink)">
                {status.status === 'running' && 'Ollama is running'}
                {status.status === 'started' && 'Ollama just started'}
                {status.status === 'not_found' && 'Bundled engine missing'}
                {status.status === 'error' && 'Error'}
              </span>
            </div>
            <p className="text-[12px] text-(--ink-muted) leading-relaxed">
              {status.message}
            </p>
            {(status.status === 'running' || status.status === 'started') && (
              <div className="mt-2 text-[11px] text-(--ok) bg-(--ok)/5 border border-(--ok)/20 rounded-md px-2.5 py-1.5">
                Ollama is listening on localhost:11434
              </div>
            )}
            {status.status === 'not_found' && (
              <p className="mt-2 text-[12px] text-(--ink-muted) leading-relaxed">
                The bundled engine could not be found. Reinstalling Obrenna should restore it.
              </p>
            )}
          </div>
        ) : (
          <div className="text-[13px] text-(--ink-muted)">
            Unable to check Ollama status.
          </div>
        )}

        <div className="mt-4 pt-3 border-t border-(--border)">
          {(status?.status !== 'running' && status?.status !== 'started') && (
            <button
              onClick={handleStart}
              disabled={starting}
              className="inline-flex items-center gap-2 h-8 px-3 rounded-md text-[13px] font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-(--accent) focus-visible:ring-offset-2 focus-visible:ring-offset-(--bg) disabled:opacity-50 disabled:pointer-events-none bg-(--accent) text-(--accent-ink) hover:brightness-110"
            >
              {starting ? 'Starting…' : 'Start Ollama'}
            </button>
          )}
          {(status?.status === 'running' || status?.status === 'started') && (
            <button
              onClick={checkStatus}
              disabled={checking}
              className="inline-flex items-center gap-2 h-8 px-3 rounded-md text-[13px] font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-(--accent) focus-visible:ring-offset-2 focus-visible:ring-offset-(--bg) disabled:opacity-50 disabled:pointer-events-none bg-(--surface-2) text-(--ink) border border-(--border) hover:bg-(--border)"
            >
              {checking ? 'Checking…' : 'Refresh status'}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
