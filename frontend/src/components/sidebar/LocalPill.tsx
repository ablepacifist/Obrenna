import { useState } from 'react'
import { ShieldCheck } from 'lucide-react'

export function LocalPill() {
  const [open, setOpen] = useState(false)
  return (
    <div className="relative">
      <button
        onClick={() => setOpen(v => !v)}
        className="h-7 px-2 rounded-full border border-(--border) bg-(--surface) inline-flex items-center gap-1.5 text-[11px] text-(--ink-muted) hover:bg-(--surface-2) focus:outline-none focus-visible:ring-2 focus-visible:ring-(--accent)"
        aria-label="Local status"
      >
        <span className="w-1.5 h-1.5 rounded-full bg-(--ok)" />
        Local
      </button>
      {open && (
        <div className="absolute bottom-9 right-0 z-40 w-[240px] rounded-lg border border-(--border) bg-(--surface) p-3 text-[12px] shadow-[0_1px_2px_rgba(28,25,22,.04),0_8px_24px_-8px_rgba(28,25,22,.10)]">
          <div className="flex items-center gap-1.5 text-(--ink) font-medium">
            <ShieldCheck className="w-3.5 h-3.5 text-(--ok)" /> Running locally
          </div>
          <div className="mt-2 text-(--ink-muted) leading-relaxed">
            Files, prompts, and outputs stay on this machine. Nothing is sent to a cloud service.
          </div>
        </div>
      )}
    </div>
  )
}
