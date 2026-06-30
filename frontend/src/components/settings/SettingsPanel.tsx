import { useEffect, useState } from 'react'
import { FileText } from 'lucide-react'
import { cn } from '../../lib/cn'
import { getAppSettings, updateAppSettings } from '../../lib/api'
import type { AppSettings } from '../../lib/api'

export function SettingsPanel() {
  const [settings, setSettings] = useState<AppSettings | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)

  // Load settings on mount
  useEffect(() => {
    getAppSettings()
      .then(setSettings)
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [])

  const updateSettings = async (updates: Partial<AppSettings>) => {
    if (!settings) return

    setSaving(true)
    try {
      const updated = { ...settings, ...updates }
      const response = await updateAppSettings(updated)
      setSettings(response)
    } catch (error) {
      console.error('Failed to update settings:', error)
      // Optionally show toast notification
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="p-4 rounded-lg border border-(--border) bg-(--surface)">
        <div className="animate-pulse">
          <div className="h-4 bg-(--border) rounded w-3/4 mb-2"></div>
          <div className="h-3 bg-(--border) rounded w-1/2"></div>
        </div>
      </div>
    )
  }

  if (!settings) {
    return (
      <div className="p-4 rounded-lg border border-(--border) bg-(--surface)">
        <p className="text-(--ink-muted)">Unable to load settings.</p>
      </div>
    )
  }

  return (
    <div className="p-4 rounded-lg border border-(--border) bg-(--surface)">
      <h3 className="text-[14px] font-medium text-(--ink) mb-3">Settings</h3>
      
      <div className="space-y-3">
        {/* Worker Models Toggle */}
        <div className="flex items-center justify-between py-2">
          <div className="flex-1">
            <label className="text-[13px] font-medium text-(--ink)">Worker Models</label>
            <p className="text-[11px] text-(--ink-muted) mt-0.5">
              Run separate utility models for context extraction and summarization.
              Disable for lower memory usage or faster responses.
            </p>
          </div>
          <button
            onClick={() => updateSettings({ workers_enabled: !settings.workers_enabled })}
            disabled={saving}
            className={cn(
              'relative inline-flex h-5 w-9 items-center rounded-full transition-colors',
              'focus:outline-none focus:ring-2 focus:ring-(--accent) focus:ring-offset-2',
              settings.workers_enabled ? 'bg-(--accent)' : 'bg-(--border)'
            )}
          >
            <span
              className={cn(
                'inline-block h-3 w-3 transform rounded-full bg-white transition-transform',
                settings.workers_enabled ? 'translate-x-4' : 'translate-x-0.5'
              )}
            />
          </button>
        </div>

        {/* Current Status */}
        <div className="mt-4 p-3 rounded-md bg-(--surface-2) border border-(--border)">
          <div className="text-[11px] text-(--ink-muted) mb-1">Current Status</div>
          <div className="flex items-center gap-2">
            <FileText className="w-3.5 h-3.5 text-(--ink-muted)" />
            <span className={cn(
              'text-[12px] font-medium',
              settings.workers_enabled ? 'text-(--accent)' : 'text-(--ink-muted)'
            )}>{
              settings.workers_enabled 
                ? 'Workers enabled — using extra memory for advanced features'
                : 'Workers disabled — using less memory, simpler responses'
            }</span>
          </div>
        </div>
      </div>
    </div>
  )
}