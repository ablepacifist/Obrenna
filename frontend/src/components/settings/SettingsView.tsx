import { X } from 'lucide-react'
import { useState } from 'react'
import { cn } from '../../lib/cn'
import { IconButton } from '../ui/IconButton'
import { ModelsSettings } from './ModelsSettings'
import { SetupSettings } from './SetupSettings'
import { AppearanceSettings } from './AppearanceSettings'
import { PrivacySettings } from './PrivacySettings'

interface SettingsViewProps {
  onClose: () => void
  onRerunSetup: () => void
}

const TABS = [
  { id: 'models', label: 'Models' },
  { id: 'setup', label: 'Setup' },
  { id: 'appearance', label: 'Appearance' },
  { id: 'privacy', label: 'Privacy' },
] as const

type TabId = typeof TABS[number]['id']

export function SettingsView({ onClose, onRerunSetup }: SettingsViewProps) {
  const [tab, setTab] = useState<TabId>('models')

  return (
    <div className="fixed inset-0 z-50 bg-black/30 flex items-center justify-center p-6">
      <div className="w-full max-w-[820px] h-[620px] max-h-[90vh] rounded-xl bg-(--bg) border border-(--border) shadow-[var(--shadow)] flex overflow-hidden relative">
        <div className="w-[180px] shrink-0 border-r border-(--border) p-3">
          <div className="px-2 pb-2 text-[11px] uppercase tracking-wide text-(--ink-faint) font-medium">Settings</div>
          <div className="space-y-0.5">
            {TABS.map(t => (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                className={cn(
                  'w-full h-8 px-2 rounded-md text-left text-[13px] focus:outline-none focus-visible:ring-2 focus-visible:ring-(--accent)',
                  tab === t.id ? 'bg-(--surface-2) text-(--ink) font-medium' : 'text-(--ink-muted) hover:bg-(--surface-2)',
                )}
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>
        <div className="flex-1 overflow-y-auto p-6">
          {tab === 'models' && <ModelsSettings />}
          {tab === 'setup' && <SetupSettings onRerunSetup={onRerunSetup} />}
          {tab === 'appearance' && <AppearanceSettings />}
          {tab === 'privacy' && <PrivacySettings />}
        </div>
        <div className="absolute top-3 right-3">
          <IconButton onClick={onClose}><X className="w-4 h-4" /></IconButton>
        </div>
      </div>
    </div>
  )
}
