import { useState } from 'react'
import { AlertTriangle, Check, FilePlus2, FileX2, Loader2, MoveRight, Terminal, X } from 'lucide-react'
import { cn } from '../../lib/cn'
import type { PendingApprovalDTO } from '../../lib/api'

/** Inline approval prompt for a write the agent wants to make.
 *
 * Rendered when the turn is SUSPENDED — the backend is blocked awaiting this
 * decision, so this card is the only thing that resumes it. Shows the exact
 * change (a real diff for edits) rather than raw JSON, because approving a
 * change you can't see is not meaningfully an approval.
 */

export type ApprovalDecision = 'approve' | 'reject'

interface ApprovalCardProps {
  approval: PendingApprovalDTO
  onDecide: (approvalId: string, decision: ApprovalDecision) => void
  /** Set once a decision is in flight or settled, so the card stops soliciting input. */
  settled?: ApprovalDecision | 'pending'
}

function str(v: unknown): string {
  return typeof v === 'string' ? v : ''
}

/** Line-level +/- rendering of an edit's before/after. */
function EditDiff({ oldString, newString }: { oldString: string; newString: string }) {
  return (
    <div className="mt-2 rounded-md border border-(--border) overflow-hidden text-[11px] font-mono">
      {oldString && (
        <div className="bg-red-500/10 text-red-600 dark:text-red-400 px-2 py-1 overflow-x-auto">
          {oldString.split('\n').map((line, i) => (
            <div key={i} className="whitespace-pre">- {line}</div>
          ))}
        </div>
      )}
      {newString && (
        <div className="bg-green-500/10 text-green-700 dark:text-green-400 px-2 py-1 overflow-x-auto">
          {newString.split('\n').map((line, i) => (
            <div key={i} className="whitespace-pre">+ {line}</div>
          ))}
        </div>
      )}
    </div>
  )
}

/** One-line human summary of what's being asked, per tool. */
function describe(approval: PendingApprovalDTO): { icon: React.ReactNode; title: string; subject: string } {
  const a = approval.arguments || {}
  const path = str(a.path)
  switch (approval.tool_name) {
    case 'codebase_edit_file':
      return { icon: <FilePlus2 className="w-3.5 h-3.5" />, title: 'Edit file', subject: path }
    case 'codebase_write_file':
      return { icon: <FilePlus2 className="w-3.5 h-3.5" />, title: 'Write file', subject: path }
    case 'codebase_delete_file':
      return { icon: <FileX2 className="w-3.5 h-3.5" />, title: 'Delete file', subject: path }
    case 'codebase_move_file':
      return {
        icon: <MoveRight className="w-3.5 h-3.5" />,
        title: 'Move file',
        subject: `${path} → ${str(a.new_path)}`,
      }
    case 'codebase_run_command':
      return { icon: <Terminal className="w-3.5 h-3.5" />, title: 'Run command', subject: str(a.command) }
    default:
      return { icon: <AlertTriangle className="w-3.5 h-3.5" />, title: approval.tool_name, subject: path }
  }
}

export function ApprovalCard({ approval, onDecide, settled }: ApprovalCardProps) {
  const [busy, setBusy] = useState<ApprovalDecision | null>(null)
  const { icon, title, subject } = describe(approval)
  const a = approval.arguments || {}
  const oldString = str(a.old_string)
  const newString = str(a.new_string)
  const content = str(a.content)
  const isDone = settled === 'approve' || settled === 'reject'

  const decide = (decision: ApprovalDecision) => {
    if (busy || isDone) return
    setBusy(decision)
    onDecide(approval.approval_id, decision)
  }

  return (
    <div
      className={cn(
        'rounded-lg border px-3 py-2.5 text-[12px] transition-colors',
        isDone ? 'border-(--border) bg-(--surface-2)' : 'border-(--accent)/50 bg-(--accent)/5',
      )}
    >
      <div className="flex items-center gap-2">
        <span className={cn('shrink-0', isDone ? 'text-(--ink-muted)' : 'text-(--accent)')}>{icon}</span>
        <span className="font-medium text-(--ink)">{title}</span>
        {subject && (
          <span className="text-(--ink-muted) font-mono text-[11px] truncate min-w-0">{subject}</span>
        )}
        {isDone && (
          <span
            className={cn(
              'ml-auto shrink-0 text-[11px] font-medium',
              settled === 'approve' ? 'text-(--accent)' : 'text-(--ink-faint)',
            )}
          >
            {settled === 'approve' ? 'Approved' : 'Rejected'}
          </span>
        )}
      </div>

      {/* The change itself. An edit shows a diff; a full write shows the body
          it would land, truncated so a huge file can't swamp the thread. */}
      {(oldString || newString) ? (
        <EditDiff oldString={oldString} newString={newString} />
      ) : content ? (
        <pre className="mt-2 rounded-md border border-(--border) bg-(--surface) px-2 py-1 text-[11px] font-mono overflow-x-auto max-h-[240px] whitespace-pre">
          {content.length > 4000 ? content.slice(0, 4000) + '\n… (truncated)' : content}
        </pre>
      ) : null}

      {!isDone && (
        <div className="mt-2.5 flex items-center gap-2">
          <button
            onClick={() => decide('approve')}
            disabled={!!busy}
            className={cn(
              'h-7 px-3 rounded-md text-[12px] font-medium inline-flex items-center gap-1.5 transition-colors',
              'bg-(--accent) text-white hover:opacity-90 disabled:opacity-60',
            )}
          >
            {busy === 'approve' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
            Approve
          </button>
          <button
            onClick={() => decide('reject')}
            disabled={!!busy}
            className={cn(
              'h-7 px-3 rounded-md text-[12px] inline-flex items-center gap-1.5 border transition-colors',
              'border-(--border) text-(--ink-muted) hover:text-(--ink) hover:border-(--ink-faint) disabled:opacity-60',
            )}
          >
            {busy === 'reject' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <X className="w-3.5 h-3.5" />}
            Reject
          </button>
          <span className="text-(--ink-faint) text-[11px]">Waiting for you — the turn is paused.</span>
        </div>
      )}
    </div>
  )
}
