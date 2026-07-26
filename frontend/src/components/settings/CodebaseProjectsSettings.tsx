import { useEffect, useState } from 'react'
import { Check, FolderCog, Plus, Trash2, X } from 'lucide-react'
import {
  getCodebaseAgentDevices,
  approveCodebaseAgentDevice,
  deleteCodebaseAgentDevice,
  getCodebaseProjects,
  createCodebaseProject,
  updateCodebaseProject,
  deleteCodebaseProject,
  type CodebaseAgentDeviceDTO,
  type CodebaseProjectDTO,
} from '../../lib/api'

const emptyForm = { name: '', device_id: '', root_path: '', write_enabled: false }

function timeAgo(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diffMs / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.floor(hours / 24)}d ago`
}

export function CodebaseProjectsSettings() {
  const [devices, setDevices] = useState<CodebaseAgentDeviceDTO[]>([])
  const [projects, setProjects] = useState<CodebaseProjectDTO[]>([])
  const [loading, setLoading] = useState(true)
  const [adding, setAdding] = useState(false)
  const [form, setForm] = useState(emptyForm)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  const refresh = () => {
    Promise.all([getCodebaseAgentDevices(), getCodebaseProjects()])
      .then(([d, p]) => { setDevices(d); setProjects(p) })
      .catch(() => {})
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    refresh()
    const interval = setInterval(refresh, 5000)
    return () => clearInterval(interval)
  }, [])

  const pending = devices.filter(d => !d.approved)
  const approved = devices.filter(d => d.approved)

  const handleApprove = async (id: string) => {
    try {
      await approveCodebaseAgentDevice(id)
      refresh()
    } catch {
      // silently fail
    }
  }

  const handleDenyOrRemove = async (id: string) => {
    try {
      await deleteCodebaseAgentDevice(id)
      refresh()
    } catch {
      // silently fail
    }
  }

  const handleCreateProject = async () => {
    if (!form.name.trim() || !form.device_id || !form.root_path.trim()) return
    setSaving(true)
    setError(null)
    try {
      const project = await createCodebaseProject(form)
      setProjects(prev => [project, ...prev])
      setForm(emptyForm)
      setAdding(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to pair project')
    } finally {
      setSaving(false)
    }
  }

  const handleToggleProject = async (project: CodebaseProjectDTO, field: 'write_enabled' | 'enabled') => {
    try {
      const updated = await updateCodebaseProject(project.id, { [field]: !project[field] })
      setProjects(prev => prev.map(p => (p.id === project.id ? updated : p)))
    } catch {
      // silently fail
    }
  }

  const handleDeleteProject = async (id: string) => {
    try {
      await deleteCodebaseProject(id)
      setProjects(prev => prev.filter(p => p.id !== id))
    } catch {
      // silently fail
    }
  }

  return (
    <div>
      <h3 className="text-[18px] font-semibold tracking-tight text-(--ink)">Codebase Projects</h3>
      <p className="mt-1 text-[13px] text-(--ink-muted) leading-relaxed">
        Run the codebase agent on any machine you want the assistant to work with, pointed at{' '}
        <strong>this same address</strong> you use to reach Obrenna — no separate address or token to
        set up:
      </p>
      <div className="mt-2 rounded-lg bg-(--surface-2) px-3 py-2 font-mono text-[12px] text-(--ink) overflow-x-auto">
        python -m codebase_agent.main --server {typeof window !== 'undefined' ? window.location.origin : '<this-address>'}
      </div>

      {/* Pending devices */}
      {loading ? (
        <div className="mt-4 text-[13px] text-(--ink-muted)">Loading...</div>
      ) : pending.length > 0 && (
        <div className="mt-5">
          <div className="text-[11px] uppercase tracking-wide text-(--ink-faint) font-medium mb-2">
            Waiting for approval
          </div>
          <div className="space-y-2">
            {pending.map(d => (
              <div key={d.id} className="rounded-xl border border-(--accent)/40 bg-(--accent)/5 p-3 flex items-center gap-3">
                <FolderCog className="w-4 h-4 text-(--accent) shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="text-[13px] font-medium text-(--ink)">{d.name}</div>
                  <div className="text-[11px] text-(--ink-faint)">
                    {d.connected ? 'connected' : 'not connected'} · first seen {timeAgo(d.created_at)}
                  </div>
                </div>
                <button
                  onClick={() => handleApprove(d.id)}
                  className="px-2.5 py-1.5 text-[12px] rounded-md bg-(--accent) text-white hover:opacity-90 inline-flex items-center gap-1"
                >
                  <Check className="w-3.5 h-3.5" /> Approve
                </button>
                <button
                  onClick={() => handleDenyOrRemove(d.id)}
                  className="p-1.5 rounded-md text-(--ink-faint) hover:text-red-500 hover:bg-(--surface-2)"
                  title="Deny"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Approved devices */}
      {approved.length > 0 && (
        <div className="mt-5">
          <div className="text-[11px] uppercase tracking-wide text-(--ink-faint) font-medium mb-2">Devices</div>
          <div className="space-y-2">
            {approved.map(d => (
              <div key={d.id} className="rounded-xl border border-(--border) bg-(--surface) p-3 flex items-center gap-3">
                <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${d.connected ? 'bg-(--ok)' : 'bg-(--ink-faint)'}`} />
                <div className="flex-1 min-w-0">
                  <div className="text-[13px] font-medium text-(--ink)">{d.name}</div>
                  <div className="text-[11px] text-(--ink-faint)">
                    {d.connected ? 'connected' : `last seen ${timeAgo(d.last_seen_at)}`}
                  </div>
                </div>
                <button
                  onClick={() => handleDenyOrRemove(d.id)}
                  className="p-1.5 rounded-md text-(--ink-faint) hover:text-red-500 hover:bg-(--surface-2)"
                  title="Remove device"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Projects */}
      <div className="mt-5">
        <div className="text-[11px] uppercase tracking-wide text-(--ink-faint) font-medium mb-2">Projects</div>

        {adding && (
          <div className="rounded-xl border border-(--border) bg-(--surface) p-4 space-y-3">
            <input
              value={form.name}
              onChange={e => setForm({ ...form, name: e.target.value })}
              placeholder="Project name (e.g. my-app)"
              className="w-full text-[13px] text-(--ink) bg-transparent outline-none placeholder:text-(--ink-faint) border-b border-(--border) pb-2"
              autoFocus
            />
            <select
              value={form.device_id}
              onChange={e => setForm({ ...form, device_id: e.target.value })}
              className="w-full text-[13px] text-(--ink) bg-(--surface-2) rounded-lg px-2 py-1.5 outline-none"
            >
              <option value="">Select a device...</option>
              {approved.map(d => (
                <option key={d.device_id} value={d.device_id}>{d.name}{d.connected ? '' : ' (offline)'}</option>
              ))}
            </select>
            <input
              value={form.root_path}
              onChange={e => setForm({ ...form, root_path: e.target.value })}
              placeholder="Folder path on that device (e.g. C:\code\my-app)"
              className="w-full text-[13px] text-(--ink) bg-transparent outline-none placeholder:text-(--ink-faint) border-b border-(--border) pb-2"
            />
            <label className="flex items-center gap-2 text-[13px] text-(--ink-muted)">
              <input
                type="checkbox"
                checked={form.write_enabled}
                onChange={e => setForm({ ...form, write_enabled: e.target.checked })}
              />
              Allow the assistant to edit files in this project (not just read)
            </label>
            {error && <div className="text-[12px] text-(--err)">{error}</div>}
            <div className="flex justify-end gap-2 pt-1">
              <button
                onClick={() => { setAdding(false); setForm(emptyForm); setError(null) }}
                className="px-3 py-1.5 text-[12px] rounded-lg border border-(--border) text-(--ink-muted) hover:bg-(--surface-2)"
              >
                Cancel
              </button>
              <button
                onClick={handleCreateProject}
                disabled={saving}
                className="px-3 py-1.5 text-[12px] rounded-lg bg-(--accent) text-white hover:opacity-90 disabled:opacity-50"
              >
                {saving ? 'Pairing...' : 'Pair project'}
              </button>
            </div>
          </div>
        )}

        {!adding && (
          <button
            onClick={() => setAdding(true)}
            disabled={approved.length === 0}
            className="flex items-center gap-1.5 px-3 py-2 text-[13px] text-(--ink-muted) border border-dashed border-(--border) rounded-xl hover:border-(--ink-muted) hover:text-(--ink) w-full justify-center disabled:opacity-40 disabled:cursor-not-allowed"
            title={approved.length === 0 ? 'Approve a device first' : undefined}
          >
            <Plus className="w-3.5 h-3.5" />
            Pair a project
          </button>
        )}

        <div className="mt-3 space-y-2">
          {projects.length === 0 && !adding ? (
            <div className="p-6 rounded-xl border border-(--border) bg-(--surface) text-center">
              <div className="text-[13px] text-(--ink-muted)">
                No projects paired yet. Approve a device above, then pair a folder on it.
              </div>
            </div>
          ) : (
            projects.map(project => {
              const device = devices.find(d => d.device_id === project.device_id)
              return (
                <div key={project.id} className="rounded-xl border border-(--border) bg-(--surface) p-4 flex items-start gap-3">
                  <FolderCog className="w-4 h-4 text-(--ink-faint) shrink-0 mt-0.5" />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-[13px] font-medium text-(--ink)">{project.name}</span>
                      {!project.enabled && (
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-(--surface-2) text-(--ink-faint)">disabled</span>
                      )}
                    </div>
                    <div className="mt-1 text-[11px] text-(--ink-faint) truncate">{project.root_path}</div>
                    <div className="text-[11px] text-(--ink-faint)">
                      on {device?.name ?? 'unknown device'} {device?.connected ? '' : '(offline)'}
                    </div>
                  </div>
                  <div className="flex items-center gap-1 shrink-0">
                    <button
                      onClick={() => handleToggleProject(project, 'write_enabled')}
                      className="px-2 py-1 text-[11px] rounded-md border border-(--border) text-(--ink-muted) hover:bg-(--surface-2)"
                    >
                      {project.write_enabled ? 'Writes: on' : 'Writes: off'}
                    </button>
                    <button
                      onClick={() => handleDeleteProject(project.id)}
                      className="p-1.5 rounded-md text-(--ink-faint) hover:text-red-500 hover:bg-(--surface-2)"
                      title="Unpair"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              )
            })
          )}
        </div>
      </div>
    </div>
  )
}
