import { RefreshCw } from 'lucide-react'
import { useEffect, useState } from 'react'
import { getAppSettings } from '../../lib/api'
import { Button } from '../ui/Button'

interface SetupSettingsProps {
  onRerunSetup: () => void
}

export function SetupSettings({ onRerunSetup }: SetupSettingsProps) {
  const [setupMode, setSetupMode] = useState<string>('managed')
  useEffect(() => {
    getAppSettings().then(s => setSetupMode(s.setup_mode)).catch(() => {})
  }, [])
  return (
    <div>
      <h3 className="text-[18px] font-semibold tracking-tight text-(--ink)">Setup</h3>
      <p className="mt-1 text-[13px] text-(--ink-muted) leading-relaxed">
        Current mode:{' '}
        <span className="text-(--ink) font-medium">
          {setupMode === 'managed' ? 'Set it up for me' : 'Connect my own local server'}
        </span>.
      </p>
      <div className="mt-5 space-y-2">
        <Button variant="secondary" onClick={onRerunSetup}>
          <RefreshCw className="w-3.5 h-3.5" /> Switch setup mode
        </Button>
        <p className="text-[12px] text-(--ink-muted) leading-relaxed">
          Switching will re-run the setup flow. Your chat history and files stay on the machine.
        </p>
      </div>
    </div>
  )
}
