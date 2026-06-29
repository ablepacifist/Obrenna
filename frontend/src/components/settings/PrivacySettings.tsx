import { ShieldCheck } from 'lucide-react'

const ROWS = [
  { label: 'Where your files are stored', value: 'On this machine, in your user folder' },
  { label: 'Where prompts and outputs are stored', value: 'On this machine only' },
  { label: 'Cloud services used', value: 'None. The app does not contact external servers.' },
  { label: 'Telemetry', value: 'None collected' },
]

export function PrivacySettings() {
  return (
    <div>
      <h3 className="text-[18px] font-semibold tracking-tight text-(--ink)">Privacy</h3>
      <p className="mt-1 text-[13px] text-(--ink-muted) leading-relaxed">
        A plain-language summary of where your data lives and what the app does with it.
      </p>
      <div className="mt-5 space-y-3">
        {ROWS.map(r => (
          <div key={r.label} className="rounded-xl border border-(--border) bg-(--surface) p-4 flex items-start justify-between gap-4">
            <div className="text-[13px] text-(--ink-muted)">{r.label}</div>
            <div className="text-[13px] text-(--ink) text-right max-w-[60%]">{r.value}</div>
          </div>
        ))}
      </div>
      <div className="mt-5 p-4 rounded-xl border border-(--border) bg-(--surface-2) flex items-start gap-3">
        <ShieldCheck className="w-4 h-4 text-(--ok) shrink-0 mt-0.5" />
        <div className="text-[13px] text-(--ink) leading-relaxed">
          If you ever want to remove everything the app has stored, open the app menu and choose{' '}
          <span className="font-medium">Reset workspace</span>. This deletes all chats, files, and models from this machine.
        </div>
      </div>
    </div>
  )
}
