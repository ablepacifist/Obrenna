import { Check, Loader2, Wrench } from 'lucide-react'
import type { MessageBlock } from '../../lib/api'

type ToolBlock = Extract<MessageBlock, { kind: 'tool' }>

interface ToolCallCardProps {
  block: ToolBlock
}

/** Compact inline tool-call card for the interleaved message cadence.
 *
 * Renders inside the ordered block list (prose → tool card → prose → tool card)
 * both during streaming (ChatThread's PendingAssistant) and after `done`
 * (MessageBubble), so the cadence persists across the done-transition within
 * a session.
 *
 * The headline is a helper-model narration of what the tool is doing
 * (`block.description`); the raw args JSON is collapsed behind a disclosure so
 * power users can still inspect it. A `Running <tool>…` placeholder fills the
 * headline until narration lands. */
function CodebaseEditDiff({ path, oldString, newString }: { path: string; oldString: string; newString: string }) {
  return (
    <div className="mt-1.5 rounded-md border border-(--border) overflow-hidden text-[11px] font-mono">
      <div className="px-2 py-1 bg-(--surface) text-(--ink-faint) border-b border-(--border) truncate">{path}</div>
      <div className="bg-red-500/10 text-red-600 dark:text-red-400 px-2 py-1 whitespace-pre-wrap break-all">
        {oldString.split('\n').map((line, i) => <div key={i}>- {line}</div>)}
      </div>
      <div className="bg-green-500/10 text-green-700 dark:text-green-400 px-2 py-1 whitespace-pre-wrap break-all">
        {newString.split('\n').map((line, i) => <div key={i}>+ {line}</div>)}
      </div>
    </div>
  )
}

export function ToolCallCard({ block }: ToolCallCardProps) {
  let argStr = ''
  try {
    const s = JSON.stringify(block.args)
    argStr = s && s !== '{}' ? s : ''
  } catch {
    argStr = ''
  }
  const headline = block.description || (block.status === 'running' ? `Running ${block.toolName || 'tool'}…` : '')
  const isCodebaseEdit = block.toolName === 'codebase_edit_file'
    && typeof block.args.old_string === 'string'
    && typeof block.args.new_string === 'string'
  return (
    <div className="rounded-lg border border-(--border) bg-(--surface-2) px-3 py-2 text-[12px]">
      <div className="flex items-center gap-2 text-(--ink-muted)">
        <Wrench className="w-3 h-3 shrink-0" />
        <span className="font-medium text-(--ink) truncate">{block.toolName || 'tool'}</span>
        <span className="ml-auto shrink-0">
          {block.status === 'running' && <Loader2 className="w-3 h-3 animate-spin" />}
          {block.status === 'done' && <Check className="w-3 h-3 text-(--accent)" />}
          {block.status === 'error' && <span className="text-red-500">error</span>}
        </span>
      </div>
      {headline && (
        <div className="mt-1 text-(--ink-muted) line-clamp-2 break-words">{headline}</div>
      )}
      {isCodebaseEdit ? (
        <CodebaseEditDiff
          path={String(block.args.path ?? '')}
          oldString={block.args.old_string as string}
          newString={block.args.new_string as string}
        />
      ) : (
        argStr && (
          <details className="mt-1 group">
            <summary className="cursor-pointer text-(--ink-faint) text-[11px] hover:text-(--ink-muted) select-none">
              Show inputs
            </summary>
            <div className="mt-1 text-(--ink-faint) break-all font-mono text-[11px]">{argStr}</div>
          </details>
        )
      )}
      {block.summary && block.status === 'done' && (
        <div className="mt-1 text-(--ink-muted) line-clamp-2 break-words">{block.summary}</div>
      )}
    </div>
  )
}