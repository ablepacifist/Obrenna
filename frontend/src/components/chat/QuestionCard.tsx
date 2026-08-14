import { useState } from 'react'
import { CircleHelp, Loader2, Send } from 'lucide-react'
import { cn } from '../../lib/cn'

/** Inline prompt for an `ask_user` question.
 *
 * Rendered when the turn is SUSPENDED — the backend is blocked awaiting this
 * answer, so this card is the only thing that resumes it. Offers one-click
 * options when the agent supplied them, and always allows a free-text answer,
 * since the right answer often isn't one of the suggestions.
 */

interface QuestionCardProps {
  questionId: string
  question: string
  options?: string[]
  /** The submitted answer once settled; undefined while still awaiting one. */
  answer?: string
  onAnswer: (questionId: string, answer: string) => void
}

export function QuestionCard({ questionId, question, options = [], answer, onAnswer }: QuestionCardProps) {
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const settled = answer !== undefined

  const submit = (value: string) => {
    const v = value.trim()
    if (!v || busy || settled) return
    setBusy(true)
    onAnswer(questionId, v)
  }

  return (
    <div
      className={cn(
        'rounded-lg border px-3 py-2.5 text-[12px] transition-colors',
        settled ? 'border-(--border) bg-(--surface-2)' : 'border-(--accent)/50 bg-(--accent)/5',
      )}
    >
      <div className="flex items-start gap-2">
        <CircleHelp className={cn('w-3.5 h-3.5 shrink-0 mt-0.5', settled ? 'text-(--ink-muted)' : 'text-(--accent)')} />
        <div className="min-w-0 flex-1">
          <div className="text-(--ink) text-[13px] break-words">{question}</div>

          {settled ? (
            <div className="mt-1.5 text-(--ink-muted) break-words">
              <span className="text-(--ink-faint)">Your answer: </span>{answer}
            </div>
          ) : (
            <>
              {options.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {options.map((opt, i) => (
                    <button
                      key={i}
                      onClick={() => submit(opt)}
                      disabled={busy}
                      className={cn(
                        'h-7 px-2.5 rounded-md text-[12px] border transition-colors',
                        'border-(--border) bg-(--surface) text-(--ink) hover:border-(--accent) hover:text-(--accent) disabled:opacity-60',
                      )}
                    >
                      {opt}
                    </button>
                  ))}
                </div>
              )}
              <div className="mt-2 flex items-center gap-1.5">
                <input
                  value={draft}
                  onChange={e => setDraft(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); submit(draft) } }}
                  disabled={busy}
                  placeholder={options.length > 0 ? 'Or type your own answer…' : 'Type your answer…'}
                  autoFocus
                  className="flex-1 min-w-0 h-8 px-2 rounded-md border border-(--border) bg-(--surface) text-[12px] text-(--ink) placeholder:text-(--ink-faint) focus:outline-none focus:border-(--accent)"
                />
                <button
                  onClick={() => submit(draft)}
                  disabled={busy || !draft.trim()}
                  className="h-8 px-2.5 rounded-md bg-(--accent) text-white text-[12px] inline-flex items-center gap-1.5 hover:opacity-90 disabled:opacity-40"
                >
                  {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />}
                  Send
                </button>
              </div>
              <div className="mt-1.5 text-(--ink-faint) text-[11px]">
                Waiting for you — the turn is paused.
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
