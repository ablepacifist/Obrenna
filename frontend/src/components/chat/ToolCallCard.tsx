import { Check, FileX2, Loader2, MoveRight, Search, Terminal, Wrench } from 'lucide-react'
import type { MessageBlock } from '../../lib/api'

type ToolBlock = Extract<MessageBlock, { kind: 'tool' }>

interface ToolCallCardProps {
  block: ToolBlock
}

/** Compact inline tool-call card for the interleaved message cadence.
 *
 * Renders inside the ordered block list (prose → tool card → prose → tool card)
 * both during streaming (ChatThread's PendingAssistant) and after `done`
 * (MessageBubble). Blocks are persisted server-side, so this is also what a
 * reloaded transcript replays — which is why the file-changing tools render a
 * real diff/summary here rather than raw JSON.
 *
 * The headline is a helper-model narration of what the tool is doing
 * (`block.description`); the raw args JSON is collapsed behind a disclosure so
 * power users can still inspect it. A `Running <tool>…` placeholder fills the
 * headline until narration lands. */

function str(v: unknown): string {
  return typeof v === 'string' ? v : ''
}

/** Line-level +/- rendering. Used for edits (old→new) and for a created file
 *  (all-additions), so every write shows what actually changed. */
function DiffBody({ oldString, newString }: { oldString: string; newString: string }) {
  return (
    <div className="mt-1.5 rounded-md border border-(--border) overflow-hidden text-[11px] font-mono">
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

function PathHeader({ children }: { children: React.ReactNode }) {
  return (
    <div className="mt-1.5 px-2 py-1 rounded-md border border-(--border) bg-(--surface) text-(--ink-muted) text-[11px] font-mono truncate">
      {children}
    </div>
  )
}

/** What a file-changing tool did, rendered per tool. Returns null for
 *  everything else so read-only tools keep the compact args disclosure. */
function ChangeDetail({ block }: { block: ToolBlock }) {
  const a = block.args || {}
  const path = str(a.path)

  switch (block.toolName) {
    // ask_user isn't really a "tool call" to the reader — it's the question the
    // agent stopped to ask. Render it as the exchange it was, so a reloaded
    // transcript shows the Q&A instead of an opaque tool card.
    case 'ask_user': {
      const question = str(a.question)
      if (!question) return null
      return (
        <div className="mt-1.5 px-2 py-1.5 rounded-md border border-(--border) bg-(--surface) text-[11px]">
          <div className="text-(--ink) break-words">{question}</div>
        </div>
      )
    }
    case 'codebase_edit_file': {
      const oldString = str(a.old_string)
      const newString = str(a.new_string)
      if (!oldString && !newString) return null
      return (
        <>
          {path && <PathHeader>{path}</PathHeader>}
          <DiffBody oldString={oldString} newString={newString} />
        </>
      )
    }
    case 'codebase_write_file': {
      // A whole-file write is all additions — show it as such rather than as
      // an opaque blob of args.
      const content = str(a.content)
      return (
        <>
          {path && <PathHeader>{path}</PathHeader>}
          {content && <DiffBody oldString="" newString={content} />}
        </>
      )
    }
    case 'codebase_delete_file':
      return (
        <div className="mt-1.5 px-2 py-1 rounded-md border border-(--border) bg-red-500/10 text-red-600 dark:text-red-400 text-[11px] font-mono flex items-center gap-1.5 overflow-x-auto">
          <FileX2 className="w-3 h-3 shrink-0" />
          <span className="whitespace-pre">deleted {path}</span>
        </div>
      )
    case 'codebase_move_file':
      return (
        <div className="mt-1.5 px-2 py-1 rounded-md border border-(--border) bg-(--surface) text-(--ink-muted) text-[11px] font-mono flex items-center gap-1.5 overflow-x-auto">
          <span className="whitespace-pre">{path}</span>
          <MoveRight className="w-3 h-3 shrink-0" />
          <span className="whitespace-pre">{str(a.new_path)}</span>
        </div>
      )
    case 'codebase_run_command': {
      const command = str(a.command)
      if (!command) return null
      const r = block.result
      const failed = r ? r.timedOut || (r.exitCode !== undefined && r.exitCode !== 0) : false
      return (
        <>
          <div className="mt-1.5 px-2 py-1 rounded-md border border-(--border) bg-(--surface) text-(--ink) text-[11px] font-mono flex items-start gap-1.5 overflow-x-auto">
            <Terminal className="w-3 h-3 shrink-0 mt-0.5 text-(--ink-faint)" />
            <span className="whitespace-pre">{command}</span>
          </div>
          {/* The output. Without this the card showed that a command ran and
              never what it printed — the single thing the user wanted to see. */}
          {r && (r.stdout || r.stderr || r.exitCode !== undefined) && (
            <div className="mt-1 rounded-md border border-(--border) overflow-hidden">
              {r.stdout && <OutputStream text={r.stdout} />}
              {r.stderr && <OutputStream text={r.stderr} tone="error" />}
              <div className={`px-2 py-0.5 text-[10px] font-mono ${
                failed ? 'bg-red-500/10 text-red-600 dark:text-red-400' : 'bg-(--surface) text-(--ink-faint)'
              }`}>
                {r.timedOut ? 'timed out' : `exit ${r.exitCode ?? '?'}`}
              </div>
            </div>
          )}
        </>
      )
    }
    case 'codebase_search': {
      const pattern = str(a.pattern)
      const r = block.result
      if (!pattern && !r) return null
      return (
        <>
          {pattern && (
            <div className="mt-1.5 px-2 py-1 rounded-md border border-(--border) bg-(--surface) text-(--ink) text-[11px] font-mono flex items-start gap-1.5 overflow-x-auto">
              <Search className="w-3 h-3 shrink-0 mt-0.5 text-(--ink-faint)" />
              <span className="whitespace-pre">{pattern}</span>
            </div>
          )}
          {r?.matchCount !== undefined && (
            <div className="mt-1 px-2 py-1 rounded-md border border-(--border) bg-(--surface) text-[11px]">
              <div className="text-(--ink-muted)">
                {r.matchCount === 0
                  ? 'no matches'
                  : `${r.matchCount} match${r.matchCount === 1 ? '' : 'es'}${r.truncated ? ' (capped)' : ''}`}
              </div>
              {r.paths?.map(p => (
                <div key={p} className="font-mono text-(--ink-faint) truncate">{p}</div>
              ))}
            </div>
          )}
        </>
      )
    }
    case 'codebase_read_file': {
      const shown = path || str(block.result?.path)
      if (!shown) return null
      const lines = block.result?.lineCount
      return (
        <PathHeader>
          {shown}
          {lines !== undefined && <span className="text-(--ink-faint)"> · {lines} lines</span>}
          {block.result?.truncated && <span className="text-(--ink-faint)"> · truncated</span>}
        </PathHeader>
      )
    }
    case 'codebase_list_directory': {
      const count = block.result?.entryCount
      return (
        <PathHeader>
          {path || '.'}
          {count !== undefined && (
            <span className="text-(--ink-faint)">
              {' '}· {count} entr{count === 1 ? 'y' : 'ies'}{block.result?.truncated ? '+' : ''}
            </span>
          )}
        </PathHeader>
      )
    }
    default:
      return null
  }
}

/** A captured stdout/stderr stream, scrollable so a long log doesn't take over
 *  the transcript. */
function OutputStream({ text, tone }: { text: string; tone?: 'error' }) {
  return (
    <div
      className={`px-2 py-1 max-h-48 overflow-auto text-[11px] font-mono whitespace-pre-wrap break-words ${
        tone === 'error'
          ? 'bg-red-500/5 text-red-600 dark:text-red-400'
          : 'bg-(--surface) text-(--ink-muted)'
      }`}
    >
      {text}
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
  const detail = <ChangeDetail block={block} />

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
      {detail ?? (
        argStr && (
          <details className="mt-1 group">
            <summary className="cursor-pointer text-(--ink-faint) text-[11px] hover:text-(--ink-muted) select-none">
              Show inputs
            </summary>
            <div className="mt-1 text-(--ink-faint) break-all font-mono text-[11px]">{argStr}</div>
          </details>
        )
      )}
      {/* The reason a call failed lives in `summary`, and this used to render
          only on 'done' — so a failed tool showed the word "error" and nothing
          else, leaving no way to tell a missing file from a disconnected
          device. Errors are shown in full rather than clamped: the message is
          the whole point, and it now carries the recovery ("...exists at
          docs/X. Retry with that path"). */}
      {block.summary && (
        block.status === 'error' ? (
          <div className="mt-1 px-2 py-1 rounded-md border border-red-500/30 bg-red-500/10 text-red-600 dark:text-red-400 text-[11px] break-words">
            {block.summary}
          </div>
        ) : block.status === 'done' ? (
          <div className="mt-1 text-(--ink-muted) line-clamp-2 break-words">{block.summary}</div>
        ) : null
      )}
    </div>
  )
}
