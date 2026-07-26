import { useEffect, useState } from 'react'
import { Trash2, Edit2, Plus, AlertTriangle, X } from 'lucide-react'
import {
  getCustomTools,
  createCustomTool,
  updateCustomTool,
  deleteCustomTool,
  type CustomToolDTO,
  type CustomToolParamDTO,
  type CustomToolInput,
} from '../../lib/api'

const METHODS = ['GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE']
const READ_ONLY_METHODS = new Set(['GET', 'HEAD'])

type FormState = {
  name: string
  description: string
  base_url: string
  http_method: string
  headers: { key: string; value: string }[]
  params: CustomToolParamDTO[]
}

const emptyForm: FormState = {
  name: '',
  description: '',
  base_url: '',
  http_method: 'GET',
  headers: [],
  params: [],
}

function toFormState(tool: CustomToolDTO): FormState {
  return {
    name: tool.name,
    description: tool.description,
    base_url: tool.base_url,
    http_method: tool.http_method,
    headers: Object.entries(tool.headers).map(([key, value]) => ({ key, value })),
    params: tool.params,
  }
}

function toInput(form: FormState): CustomToolInput {
  const headers: Record<string, string> = {}
  for (const h of form.headers) {
    if (h.key.trim()) headers[h.key.trim()] = h.value
  }
  return {
    name: form.name.trim(),
    description: form.description.trim(),
    base_url: form.base_url.trim(),
    http_method: form.http_method,
    headers,
    params: form.params.filter(p => p.name.trim()),
  }
}

function ToolForm({
  form,
  onChange,
  onCancel,
  onSave,
  error,
}: {
  form: FormState
  onChange: (f: FormState) => void
  onCancel: () => void
  onSave: () => void
  error: string | null
}) {
  const isReadOnly = READ_ONLY_METHODS.has(form.http_method)

  return (
    <div className="rounded-xl border border-(--border) bg-(--surface) p-4 space-y-3">
      <input
        value={form.name}
        onChange={e => onChange({ ...form, name: e.target.value })}
        placeholder="Tool name (e.g. get_weather)"
        className="w-full text-[13px] text-(--ink) bg-transparent outline-none placeholder:text-(--ink-faint) border-b border-(--border) pb-2"
        autoFocus
      />
      <textarea
        value={form.description}
        onChange={e => onChange({ ...form, description: e.target.value })}
        placeholder="Description — this is what the model reads to decide when to call it"
        className="w-full text-[13px] text-(--ink) bg-transparent resize-none outline-none min-h-[50px] placeholder:text-(--ink-faint)"
      />
      <div className="flex gap-2">
        <select
          value={form.http_method}
          onChange={e => onChange({ ...form, http_method: e.target.value })}
          className="text-[13px] text-(--ink) bg-(--surface-2) rounded-lg px-2 py-1.5 outline-none"
        >
          {METHODS.map(m => (
            <option key={m} value={m}>{m}</option>
          ))}
        </select>
        <input
          value={form.base_url}
          onChange={e => onChange({ ...form, base_url: e.target.value })}
          placeholder="https://api.example.com/endpoint"
          className="flex-1 text-[13px] text-(--ink) bg-transparent outline-none placeholder:text-(--ink-faint) border-b border-(--border) pb-1.5"
        />
      </div>

      {!isReadOnly && (
        <div className="flex items-start gap-2 p-2.5 rounded-lg bg-(--err)/5 text-(--err)">
          <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
          <span className="text-[12px] leading-relaxed">
            The assistant can call this automatically during conversation, including
            submitting data — only add APIs you trust it to call on its own.
          </span>
        </div>
      )}

      <div>
        <div className="text-[11px] text-(--ink-muted) mb-1.5">Headers</div>
        {form.headers.map((h, i) => (
          <div key={i} className="flex items-center gap-1.5 mb-1.5">
            <input
              value={h.key}
              onChange={e => {
                const headers = [...form.headers]
                headers[i] = { ...headers[i], key: e.target.value }
                onChange({ ...form, headers })
              }}
              placeholder="Header name"
              className="flex-1 text-[12px] text-(--ink) bg-(--surface-2) rounded-md px-2 py-1 outline-none placeholder:text-(--ink-faint)"
            />
            <input
              value={h.value}
              onChange={e => {
                const headers = [...form.headers]
                headers[i] = { ...headers[i], value: e.target.value }
                onChange({ ...form, headers })
              }}
              placeholder="Value"
              className="flex-1 text-[12px] text-(--ink) bg-(--surface-2) rounded-md px-2 py-1 outline-none placeholder:text-(--ink-faint)"
            />
            <button
              onClick={() => onChange({ ...form, headers: form.headers.filter((_, j) => j !== i) })}
              className="p-1 text-(--ink-faint) hover:text-red-500"
            >
              <X className="w-3 h-3" />
            </button>
          </div>
        ))}
        <button
          onClick={() => onChange({ ...form, headers: [...form.headers, { key: '', value: '' }] })}
          className="text-[11px] text-(--ink-muted) hover:text-(--ink)"
        >
          + Add header
        </button>
      </div>

      <div>
        <div className="text-[11px] text-(--ink-muted) mb-1.5">Parameters</div>
        {form.params.map((p, i) => (
          <div key={i} className="flex items-center gap-1.5 mb-1.5">
            <input
              value={p.name}
              onChange={e => {
                const params = [...form.params]
                params[i] = { ...params[i], name: e.target.value }
                onChange({ ...form, params })
              }}
              placeholder="Param name"
              className="w-28 text-[12px] text-(--ink) bg-(--surface-2) rounded-md px-2 py-1 outline-none placeholder:text-(--ink-faint)"
            />
            <input
              value={p.description}
              onChange={e => {
                const params = [...form.params]
                params[i] = { ...params[i], description: e.target.value }
                onChange({ ...form, params })
              }}
              placeholder="Description"
              className="flex-1 text-[12px] text-(--ink) bg-(--surface-2) rounded-md px-2 py-1 outline-none placeholder:text-(--ink-faint)"
            />
            <select
              value={p.location}
              onChange={e => {
                const params = [...form.params]
                params[i] = { ...params[i], location: e.target.value as 'query' | 'body' }
                onChange({ ...form, params })
              }}
              disabled={isReadOnly}
              className="text-[11px] text-(--ink) bg-(--surface-2) rounded-md px-1.5 py-1 outline-none disabled:opacity-50"
            >
              <option value="query">query</option>
              <option value="body">body</option>
            </select>
            <label className="flex items-center gap-1 text-[11px] text-(--ink-muted) shrink-0">
              <input
                type="checkbox"
                checked={p.required}
                onChange={e => {
                  const params = [...form.params]
                  params[i] = { ...params[i], required: e.target.checked }
                  onChange({ ...form, params })
                }}
              />
              required
            </label>
            <button
              onClick={() => onChange({ ...form, params: form.params.filter((_, j) => j !== i) })}
              className="p-1 text-(--ink-faint) hover:text-red-500"
            >
              <X className="w-3 h-3" />
            </button>
          </div>
        ))}
        <button
          onClick={() =>
            onChange({
              ...form,
              params: [
                ...form.params,
                { name: '', description: '', required: false, location: 'query', type: 'string' },
              ],
            })
          }
          className="text-[11px] text-(--ink-muted) hover:text-(--ink)"
        >
          + Add parameter
        </button>
      </div>

      {error && <div className="text-[12px] text-(--err)">{error}</div>}

      <div className="flex justify-end gap-2 pt-1">
        <button
          onClick={onCancel}
          className="px-3 py-1.5 text-[12px] rounded-lg border border-(--border) text-(--ink-muted) hover:bg-(--surface-2)"
        >
          Cancel
        </button>
        <button
          onClick={onSave}
          className="px-3 py-1.5 text-[12px] rounded-lg bg-(--accent) text-white hover:opacity-90"
        >
          Save
        </button>
      </div>
    </div>
  )
}

export function CustomApisSettings() {
  const [tools, setTools] = useState<CustomToolDTO[]>([])
  const [loading, setLoading] = useState(true)
  const [adding, setAdding] = useState(false)
  const [addForm, setAddForm] = useState<FormState>(emptyForm)
  const [addError, setAddError] = useState<string | null>(null)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editForm, setEditForm] = useState<FormState>(emptyForm)
  const [editError, setEditError] = useState<string | null>(null)

  useEffect(() => {
    getCustomTools()
      .then(setTools)
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  const handleCreate = async () => {
    if (!addForm.name.trim() || !addForm.description.trim() || !addForm.base_url.trim()) return
    try {
      const tool = await createCustomTool(toInput(addForm))
      setTools(prev => [tool, ...prev])
      setAddForm(emptyForm)
      setAdding(false)
      setAddError(null)
    } catch (err) {
      setAddError(err instanceof Error ? err.message : 'Failed to create tool')
    }
  }

  const handleSaveEdit = async (id: string) => {
    if (!editForm.name.trim() || !editForm.description.trim() || !editForm.base_url.trim()) return
    try {
      const tool = await updateCustomTool(id, toInput(editForm))
      setTools(prev => prev.map(t => (t.id === id ? tool : t)))
      setEditingId(null)
      setEditError(null)
    } catch (err) {
      setEditError(err instanceof Error ? err.message : 'Failed to update tool')
    }
  }

  const handleDelete = async (id: string) => {
    try {
      await deleteCustomTool(id)
      setTools(prev => prev.filter(t => t.id !== id))
    } catch {
      // silently fail
    }
  }

  const handleToggleEnabled = async (tool: CustomToolDTO) => {
    try {
      const updated = await updateCustomTool(tool.id, { enabled: !tool.enabled } as Partial<CustomToolInput>)
      setTools(prev => prev.map(t => (t.id === tool.id ? updated : t)))
    } catch {
      // silently fail
    }
  }

  const startEdit = (tool: CustomToolDTO) => {
    setEditingId(tool.id)
    setEditForm(toFormState(tool))
    setEditError(null)
  }

  return (
    <div>
      <h3 className="text-[18px] font-semibold tracking-tight text-(--ink)">Custom APIs</h3>
      <p className="mt-1 text-[13px] text-(--ink-muted) leading-relaxed">
        Register external APIs the assistant can call as tools during conversation.
        Everything here runs only on this machine.
      </p>

      {adding && (
        <div className="mt-4">
          <ToolForm
            form={addForm}
            onChange={setAddForm}
            onCancel={() => { setAdding(false); setAddForm(emptyForm); setAddError(null) }}
            onSave={handleCreate}
            error={addError}
          />
        </div>
      )}

      {!adding && (
        <button
          onClick={() => setAdding(true)}
          className="mt-4 flex items-center gap-1.5 px-3 py-2 text-[13px] text-(--ink-muted) border border-dashed border-(--border) rounded-xl hover:border-(--ink-muted) hover:text-(--ink) w-full justify-center"
        >
          <Plus className="w-3.5 h-3.5" />
          Add API
        </button>
      )}

      <div className="mt-5 space-y-2">
        {loading ? (
          <div className="text-[13px] text-(--ink-muted)">Loading...</div>
        ) : tools.length === 0 ? (
          <div className="mt-3 p-6 rounded-xl border border-(--border) bg-(--surface) text-center">
            <div className="text-[13px] text-(--ink-muted)">
              No custom APIs yet. Add one above to give the assistant a new capability.
            </div>
          </div>
        ) : (
          tools.map(tool =>
            editingId === tool.id ? (
              <ToolForm
                key={tool.id}
                form={editForm}
                onChange={setEditForm}
                onCancel={() => { setEditingId(null); setEditError(null) }}
                onSave={() => handleSaveEdit(tool.id)}
                error={editError}
              />
            ) : (
              <div
                key={tool.id}
                className="rounded-xl border border-(--border) bg-(--surface) p-4 flex items-start gap-3"
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-[13px] font-medium text-(--ink)">{tool.name}</span>
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-(--surface-2) text-(--ink-muted)">
                      {tool.http_method}
                    </span>
                    {!tool.enabled && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-(--surface-2) text-(--ink-faint)">
                        disabled
                      </span>
                    )}
                  </div>
                  <div className="mt-1 text-[13px] text-(--ink-muted) leading-relaxed">{tool.description}</div>
                  <div className="mt-1 text-[11px] text-(--ink-faint) truncate">{tool.base_url}</div>
                </div>
                <div className="flex items-center gap-1 shrink-0">
                  <button
                    onClick={() => handleToggleEnabled(tool)}
                    className="px-2 py-1 text-[11px] rounded-md border border-(--border) text-(--ink-muted) hover:bg-(--surface-2)"
                  >
                    {tool.enabled ? 'Disable' : 'Enable'}
                  </button>
                  <button
                    onClick={() => startEdit(tool)}
                    className="p-1.5 rounded-md text-(--ink-faint) hover:text-(--ink) hover:bg-(--surface-2)"
                    title="Edit"
                  >
                    <Edit2 className="w-3.5 h-3.5" />
                  </button>
                  <button
                    onClick={() => handleDelete(tool.id)}
                    className="p-1.5 rounded-md text-(--ink-faint) hover:text-red-500 hover:bg-(--surface-2)"
                    title="Delete"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            )
          )
        )}
      </div>
    </div>
  )
}
