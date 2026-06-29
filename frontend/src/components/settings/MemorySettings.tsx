import { useEffect, useState } from 'react'
import { Trash2, Edit2, Check, X, ShieldCheck, Plus } from 'lucide-react'
import {
  getMemoryFacts,
  createMemoryFact,
  updateMemoryFact,
  deleteMemoryFact,
  type MemoryFactDTO,
} from '../../lib/api'

export function MemorySettings() {
  const [facts, setFacts] = useState<MemoryFactDTO[]>([])
  const [loading, setLoading] = useState(true)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editText, setEditText] = useState('')
  const [adding, setAdding] = useState(false)
  const [newText, setNewText] = useState('')

  useEffect(() => {
    getMemoryFacts()
      .then(setFacts)
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  const handleCreate = async () => {
    if (!newText.trim()) return
    try {
      const fact = await createMemoryFact(newText.trim())
      setFacts(prev => [fact, ...prev])
      setNewText('')
      setAdding(false)
    } catch {
      // silently fail
    }
  }

  const handleSaveEdit = async (id: string) => {
    if (!editText.trim()) return
    try {
      const fact = await updateMemoryFact(id, editText.trim())
      setFacts(prev => prev.map(f => (f.id === id ? fact : f)))
      setEditingId(null)
      setEditText('')
    } catch {
      // silently fail
    }
  }

  const handleDelete = async (id: string) => {
    try {
      await deleteMemoryFact(id)
      setFacts(prev => prev.filter(f => f.id !== id))
    } catch {
      // silently fail
    }
  }

  const startEdit = (fact: MemoryFactDTO) => {
    setEditingId(fact.id)
    setEditText(fact.fact_text)
  }

  return (
    <div>
      <h3 className="text-[18px] font-semibold tracking-tight text-(--ink)">Memory</h3>
      <p className="mt-1 text-[13px] text-(--ink-muted) leading-relaxed">
        Local memories the app has learned about you. You can edit or delete any memory here.
        All memories are stored only on this machine.
      </p>

      {adding && (
        <div className="mt-4 rounded-xl border border-(--border) bg-(--surface) p-4">
          <textarea
            value={newText}
            onChange={e => setNewText(e.target.value)}
            placeholder="Add a memory..."
            className="w-full text-[13px] text-(--ink) bg-transparent resize-none outline-none min-h-[60px] placeholder:text-(--ink-faint)"
            autoFocus
          />
          <div className="mt-2 flex justify-end gap-2">
            <button
              onClick={() => { setAdding(false); setNewText('') }}
              className="px-3 py-1.5 text-[12px] rounded-lg border border-(--border) text-(--ink-muted) hover:bg-(--surface-2)"
            >
              Cancel
            </button>
            <button
              onClick={handleCreate}
              className="px-3 py-1.5 text-[12px] rounded-lg bg-(--accent) text-white hover:opacity-90"
            >
              Save
            </button>
          </div>
        </div>
      )}

      {!adding && (
        <button
          onClick={() => setAdding(true)}
          className="mt-4 flex items-center gap-1.5 px-3 py-2 text-[13px] text-(--ink-muted) border border-dashed border-(--border) rounded-xl hover:border-(--ink-muted) hover:text-(--ink) w-full justify-center"
        >
          <Plus className="w-3.5 h-3.5" />
          Add memory
        </button>
      )}

      <div className="mt-5 space-y-2">
        {loading ? (
          <div className="text-[13px] text-(--ink-muted)">Loading...</div>
        ) : facts.length === 0 ? (
          <div className="mt-3 p-6 rounded-xl border border-(--border) bg-(--surface) text-center">
            <div className="text-[13px] text-(--ink-muted)">
              No memories yet. Memories are automatically learned from your conversations,
              or you can add one manually above.
            </div>
          </div>
        ) : (
          facts.map(fact => (
            <div
              key={fact.id}
              className="rounded-xl border border-(--border) bg-(--surface) p-4 flex items-start gap-3"
            >
              <div className="flex-1 min-w-0">
                {editingId === fact.id ? (
                  <>
                    <textarea
                      value={editText}
                      onChange={e => setEditText(e.target.value)}
                      className="w-full text-[13px] text-(--ink) bg-transparent resize-none outline-none min-h-[40px] placeholder:text-(--ink-faint)"
                      autoFocus
                    />
                    <div className="mt-2 flex justify-end gap-2">
                      <button
                        onClick={() => { setEditingId(null); setEditText('') }}
                        className="px-2 py-1 text-[11px] rounded-md border border-(--border) text-(--ink-muted) hover:bg-(--surface-2)"
                      >
                        Cancel
                      </button>
                      <button
                        onClick={() => handleSaveEdit(fact.id)}
                        className="px-2 py-1 text-[11px] rounded-md bg-(--accent) text-white hover:opacity-90"
                      >
                        Save
                      </button>
                    </div>
                  </>
                ) : (
                  <>
                    <div className="text-[13px] text-(--ink) leading-relaxed">{fact.fact_text}</div>
                    <div className="mt-1.5 flex items-center gap-3">
                      {fact.user_locked && (
                        <span className="flex items-center gap-1 text-[10px] text-(--ok)">
                          <ShieldCheck className="w-3 h-3" />
                          User-controlled
                        </span>
                      )}
                      <span className="text-[10px] text-(--ink-faint)">
                        Updated {new Date(fact.updated_at).toLocaleDateString()}
                      </span>
                    </div>
                  </>
                )}
              </div>
              {editingId !== fact.id && (
                <div className="flex items-center gap-1 shrink-0">
                  <button
                    onClick={() => startEdit(fact)}
                    className="p-1.5 rounded-md text-(--ink-faint) hover:text-(--ink) hover:bg-(--surface-2)"
                    title="Edit"
                  >
                    <Edit2 className="w-3.5 h-3.5" />
                  </button>
                  <button
                    onClick={() => handleDelete(fact.id)}
                    className="p-1.5 rounded-md text-(--ink-faint) hover:text-red-500 hover:bg-(--surface-2)"
                    title="Delete"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              )}
              {editingId === fact.id && (
                <div className="flex items-center gap-1 shrink-0">
                  <button
                    onClick={() => handleSaveEdit(fact.id)}
                    className="p-1.5 rounded-md text-(--ok) hover:bg-(--surface-2)"
                    title="Save"
                  >
                    <Check className="w-3.5 h-3.5" />
                  </button>
                  <button
                    onClick={() => { setEditingId(null); setEditText('') }}
                    className="p-1.5 rounded-md text-(--ink-faint) hover:text-(--ink) hover:bg-(--surface-2)"
                    title="Cancel"
                  >
                    <X className="w-3.5 h-3.5" />
                  </button>
                </div>
              )}
            </div>
          ))
        )}
      </div>

      <div className="mt-5 p-4 rounded-xl border border-(--border) bg-(--surface-2) flex items-start gap-3">
        <ShieldCheck className="w-4 h-4 text-(--ok) shrink-0 mt-0.5" />
        <div className="text-[13px] text-(--ink) leading-relaxed">
          Memories are stored locally on this machine. The app may learn facts from your conversations,
          but you have full control to edit or delete any memory at any time.
        </div>
      </div>
    </div>
  )
}
