import { useEffect, useRef, useState } from 'react'
import { ShieldCheck, AlertTriangle, WifiOff } from 'lucide-react'
import { getModelStatus, type ModelStatus } from '../../lib/api'

export function LocalPill() {
  const [open, setOpen] = useState(false)
  const [status, setStatus] = useState<ModelStatus | null>(null)
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    let cancelled = false
    const poll = () => {
      getModelStatus()
        .then(s => { if (!cancelled) setStatus(s) })
        .catch(() => { if (!cancelled) setStatus(null) })
    }
    poll()
    const id = setInterval(poll, 30_000)
    return () => { cancelled = true; clearInterval(id) }
  }, [])

  // The orchestrator is the model the user actually chats to, so the pill
  // reflects its state:
  //   green  → loaded & serving (really working, chat will respond)
  //   yellow → installed but not started (exists on disk, loads on demand)
  //   red    → runtime unreachable or model not installed at all
  const orch = status?.roles.find(r => r.role === 'orchestrator')
  const dotColor = !status
    ? 'bg-(--ink-muted)'
    : !status.connected || orch?.state === 'missing'
      ? 'bg-(--err)'
      : status.chat_ready
        ? 'bg-(--ok)'
        : 'bg-(--warn)'

  const roleStateLabel = (s: string) =>
    s === 'loaded' ? 'Loaded' : s === 'installed' ? 'Not started' : 'Not installed'
  const roleStateColor = (s: string) =>
    s === 'loaded' ? 'text-(--ok)' : s === 'installed' ? 'text-(--warn)' : 'text-(--err)'

  const handleMouseEnter = () => {
    if (closeTimer.current) clearTimeout(closeTimer.current)
    setOpen(true)
  }
  const handleMouseLeave = () => {
    closeTimer.current = setTimeout(() => setOpen(false), 150)
  }

  return (
    <div className="relative" onMouseEnter={handleMouseEnter} onMouseLeave={handleMouseLeave}>
      <button
        className="h-7 px-2 rounded-full border border-(--border) bg-(--surface) inline-flex items-center gap-1.5 text-[11px] text-(--ink-muted) hover:bg-(--surface-2) focus:outline-none focus-visible:ring-2 focus-visible:ring-(--accent)"
        aria-label="Local model status"
      >
        <span className={`w-1.5 h-1.5 rounded-full ${dotColor}`} />
        Local
      </button>

      {open && (
        <div className="absolute bottom-9 right-0 z-40 w-[240px] rounded-lg border border-(--border) bg-(--surface) p-3 text-[12px] shadow-[0_1px_2px_rgba(28,25,22,.04),0_8px_24px_-8px_rgba(28,25,22,.10)]">
          {status?.connected ? (
            <>
              <div className="flex items-center gap-1.5 text-(--ink) font-medium">
                {status.chat_ready ? (
                  <ShieldCheck className="w-3.5 h-3.5 text-(--ok)" />
                ) : (
                  <AlertTriangle className="w-3.5 h-3.5 text-(--warn)" />
                )}
                {status.chat_ready ? 'Running locally' : 'Runtime ready'}
              </div>

              {status.roles.length > 0 && (
                <div className="mt-2 flex flex-col gap-1">
                  {status.roles.map(r => (
                    <div key={r.role} className="flex items-center justify-between gap-2">
                      <span className="text-(--ink-muted)">{r.display_name}</span>
                      <span className={`text-[11px] font-medium ${roleStateColor(r.state)}`}>
                        {roleStateLabel(r.state)}
                      </span>
                    </div>
                  ))}
                </div>
              )}

              {orch?.state === 'missing' && (
                <div className="mt-2 flex items-center gap-1 text-(--err)">
                  <AlertTriangle className="w-3 h-3 shrink-0" />
                  <span>Reasoner not installed — finish setup to download it.</span>
                </div>
              )}
              {orch?.state === 'installed' && (
                <div className="mt-2 flex items-center gap-1 text-(--warn)">
                  <AlertTriangle className="w-3 h-3 shrink-0" />
                  <span>Model idle — it loads on your first message.</span>
                </div>
              )}

              <div className="mt-2 text-(--ink-muted) leading-relaxed">
                Files, prompts, and outputs stay on this machine.
              </div>
            </>
          ) : (
            <>
              <div className="flex items-center gap-1.5 text-(--ink) font-medium">
                <WifiOff className="w-3.5 h-3.5 text-(--err)" />
                Runtime unavailable
              </div>
              {status?.error && (
                <div className="mt-1.5 text-(--ink-muted) break-words">{status.error}</div>
              )}
              {!status && (
                <div className="mt-1.5 text-(--ink-muted)">Checking…</div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}
