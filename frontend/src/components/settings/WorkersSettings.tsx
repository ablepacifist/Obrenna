import { useState, useEffect } from 'react'
import { FileText, Cpu, MemoryStick, Activity } from 'lucide-react'
import { cn } from '../../lib/cn'
import { getAppSettings, updateAppSettings } from '../../lib/api'
import type { AppSettings } from '../../lib/api'

interface WorkerStat {
  role: string
  model: string
  status: 'idle' | 'running' | 'completed' | 'error'
  memory_mb: number
  cpu_percent: number
  last_run: string
}

function planModel(plan: Record<string, unknown>, role: string, fallback: string): string {
  const ref = plan[role]
  if (ref && typeof ref === 'object' && 'model' in ref && typeof ref.model === 'string') {
    return ref.model
  }
  return fallback
}

export function WorkersSettings() {
  const [settings, setSettings] = useState<AppSettings | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [workerStats, setWorkerStats] = useState<WorkerStat[]>([])

  // Load settings on mount
  useEffect(() => {
    getAppSettings()
      .then(setSettings)
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [])

  const updateWorkersSetting = async (enabled: boolean) => {
    if (!settings) return
    
    setSaving(true)
    try {
      const updated = { ...settings, workers_enabled: enabled }
      const response = await updateAppSettings(updated)
      setSettings(response)
      
      // Simulate worker status updates
      if (enabled) {
        // Simulate starting workers
        setWorkerStats([
          {
            role: 'utility',
            model: planModel(settings.managed_plan, 'utility', 'default-utility-model'),
            status: 'running',
            memory_mb: 512,
            cpu_percent: 25,
            last_run: new Date().toLocaleTimeString()
          },
          {
            role: 'summarizer',
            model: planModel(settings.managed_plan, 'summarizer', 'default-summarizer-model'),
            status: 'idle',
            memory_mb: 256,
            cpu_percent: 5,
            last_run: 'Never'
          }
        ])
      } else {
        // Simulate stopping workers
        setWorkerStats([])
      }
    } catch (error) {
      console.error('Failed to update workers setting:', error)
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
    <div className="space-y-4">
      <div>
        <h3 className="text-[14px] font-medium text-(--ink) mb-2">Worker Models</h3>
        <p className="text-[12px] text-(--ink-muted) leading-relaxed">
          Worker models run separate AI instances for utility tasks (context extraction, summarization) and memory management.
        </p>
      </div>

      {/* Main Toggle */}
      <div className="flex items-center justify-between py-3 border-b border-(--border)">
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <Cpu className="w-4 h-4 text-(--ink-muted)" />
            <label className="text-[13px] font-medium text-(--ink)">Enable Worker Models</label>
          </div>
          <p className="text-[11px] text-(--ink-muted) mt-1">
            Run separate utility models for context extraction and summarization.
            Disable for lower memory usage or faster responses.
          </p>
        </div>
        <button
          onClick={() => updateWorkersSetting(!settings.workers_enabled)}
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
        <div className="text-[11px] text-(--ink-muted) mb-2">Current Status</div>
        <div className="flex items-center gap-2 mb-2">
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
        
        {settings.workers_enabled && (
          <div className="mt-3 space-y-2">
            <div className="text-[11px] text-(--ink-muted) mb-1">Active Workers</div>
            {workerStats.map(worker => (
              <div key={worker.role} className="flex items-center justify-between p-2 rounded bg-(--bg) border border-(--border)">
                <div className="flex items-center gap-2">
                  <MemoryStick className="w-3.5 h-3.5 text-(--ink-muted)" />
                  <span className="text-[12px] text-(--ink)">{worker.role}</span>
                </div>
                <div className="flex items-center gap-3">
                  <div className="flex items-center gap-1">
                    <Activity className="w-3 h-3 text-(--ink-muted)" />
                    <span className="text-[11px] text-(--ink-muted)">{worker.cpu_percent}% CPU</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <MemoryStick className="w-3 h-3 text-(--ink-muted)" />
                    <span className="text-[11px] text-(--ink-muted)">{worker.memory_mb}MB RAM</span>
                  </div>
                  <span className={cn(
                    'text-[11px] px-2 py-0.5 rounded',
                    worker.status === 'running' && 'bg-green-100 text-green-700',
                    worker.status === 'idle' && 'bg-gray-100 text-gray-700',
                    worker.status === 'completed' && 'bg-blue-100 text-blue-700',
                    worker.status === 'error' && 'bg-red-100 text-red-700'
                  )}>{worker.status}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Impact Information */}
      <div className="mt-4 p-3 rounded-md bg-(--accent)/10 border border-(--accent)/20">
        <div className="text-[11px] font-medium text-(--accent) mb-1">Impact</div>
        <div className="text-[11px] text-(--ink) space-y-1">
          <div>• Workers consume ~512MB RAM each when active</div>
          <div>• Add ~15-30 seconds startup time</div>
          <div>• Enable advanced context extraction and summarization</div>
          <div>• Improve chat relevance with memory management</div>
        </div>
      </div>
    </div>
  )
}
