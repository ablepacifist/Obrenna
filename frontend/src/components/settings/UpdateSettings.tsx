import { CheckCircle2, Loader2, RefreshCw } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Button } from '../ui/Button'
import { checkUpdate, getAppVersion, installUpdate } from '../../lib/tauri'

export function UpdateSettings() {
  const [currentVersion, setCurrentVersion] = useState('…')
  const [updateAvailable, setUpdateAvailable] = useState(false)
  const [latestVersion, setLatestVersion] = useState<string | null>(null)
  const [description, setDescription] = useState<string | null>(null)
  const [checking, setChecking] = useState(false)
  const [installing, setInstalling] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const isDesktop = typeof window !== 'undefined' && !!(window as any).__TAURI__

  useEffect(() => {
    getAppVersion().then(v => setCurrentVersion(v)).catch(() => {})
  }, [])

  const handleCheck = async () => {
    setChecking(true)
    setError(null)
    try {
      const info = await checkUpdate()
      setUpdateAvailable(info.update_available)
      setLatestVersion(info.latest_version)
      setDescription(info.description)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Check failed')
    }
    setChecking(false)
  }

  const handleInstall = async () => {
    setInstalling(true)
    setError(null)
    try {
      await installUpdate()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Install failed')
    }
    setInstalling(false)
  }

  if (!isDesktop) {
    return (
      <div>
        <h3 className="text-[18px] font-semibold tracking-tight text-(--ink)">Updates</h3>
        <p className="mt-1 text-[13px] text-(--ink-muted)">
          Updates are only available in the desktop app.
        </p>
      </div>
    )
  }

  return (
    <div>
      <h3 className="text-[18px] font-semibold tracking-tight text-(--ink)">Updates</h3>
      <p className="mt-1 text-[13px] text-(--ink-muted)">
        Current version:{' '}
        <span className="text-(--ink) font-medium">{currentVersion}</span>
      </p>

      {updateAvailable && latestVersion && (
        <div className="mt-4 p-4 bg-(--surface) border border-(--border) rounded-lg">
          <div className="flex items-center gap-2 text-[14px] font-medium text-(--ink)">
            <RefreshCw className="w-4 h-4 text-(--accent)" />
            Update available
          </div>
          <div className="mt-2 text-[13px] text-(--ink-muted)">
            Version <span className="text-(--ink) font-medium">{latestVersion}</span> is ready to install.
          </div>
          {description && (
            <div className="mt-1 text-[12px] text-(--ink-faint) whitespace-pre-line">{description}</div>
          )}
          <div className="mt-3">
            <Button
              variant="primary"
              onClick={handleInstall}
              disabled={installing}
            >
              {installing ? (
                <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Installing…</>
              ) : (
                <>Install update</>
              )}
            </Button>
            <p className="mt-1.5 text-[11px] text-(--ink-faint)">
              The app will restart after the update is installed.
            </p>
          </div>
        </div>
      )}

      {!updateAvailable && !checking && !error && (
        <div className="mt-3 flex items-center gap-2 text-[13px] text-(--ok)">
          <CheckCircle2 className="w-4 h-4" />
          Up to date
        </div>
      )}

      <div className="mt-4">
        <Button
          variant="secondary"
          onClick={handleCheck}
          disabled={checking || installing}
        >
          {checking ? (
            <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Checking…</>
          ) : (
            <>Check for updates</>
          )}
        </Button>
      </div>

      {error && (
        <div className="mt-3 text-[12px] text-(--err)">{error}</div>
      )}
    </div>
  )
}
