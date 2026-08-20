import type { ToolResultSummary } from './api'

/** Shape a raw tool result into what the card renders.
 *
 * The live stream and the persisted transcript must agree, so this mirrors
 * `_render_result_for_block` in backend/app/routers/chat.py. Previously the
 * live path kept `resultStr.slice(0, 140)` — a truncated blob of raw JSON —
 * and the persisted path kept only an error message, so a command's output was
 * never shown either way. The user watched it run a command and never saw what
 * came back.
 */

/** Keep the END of a stream: an error is at the bottom of a log, not the top. */
export const OUTPUT_MAX_CHARS = 2000
const MAX_RESULT_PATHS = 8

function tail(value: unknown, limit: number): string {
  const text = typeof value === 'string' ? value : ''
  if (text.length <= limit) return text
  return '… (earlier output trimmed)\n' + text.slice(-limit)
}

export function summarizeToolResult(toolName: string, resultStr: string): ToolResultSummary | undefined {
  if (!resultStr) return undefined
  let parsed: Record<string, unknown>
  try {
    const value = JSON.parse(resultStr)
    if (!value || typeof value !== 'object' || Array.isArray(value)) return undefined
    parsed = value as Record<string, unknown>
  } catch {
    return undefined
  }

  if (toolName === 'codebase_run_command') {
    const out: ToolResultSummary = {}
    if ('exit_code' in parsed) out.exitCode = parsed.exit_code as number | null
    const stdout = tail(parsed.stdout, OUTPUT_MAX_CHARS)
    const stderr = tail(parsed.stderr, OUTPUT_MAX_CHARS)
    if (stdout) out.stdout = stdout
    if (stderr) out.stderr = stderr
    if (parsed.timed_out) out.timedOut = true
    return Object.keys(out).length > 0 ? out : undefined
  }

  if (toolName === 'codebase_search') {
    if (!Array.isArray(parsed.matches)) return undefined
    const paths: string[] = []
    for (const match of parsed.matches) {
      const path = match && typeof match === 'object' ? (match as Record<string, unknown>).path : null
      if (typeof path === 'string' && !paths.includes(path)) paths.push(path)
      if (paths.length >= MAX_RESULT_PATHS) break
    }
    return { matchCount: parsed.matches.length, paths, truncated: Boolean(parsed.truncated) }
  }

  if (toolName === 'codebase_read_file') {
    const out: ToolResultSummary = { path: typeof parsed.path === 'string' ? parsed.path : '' }
    if (typeof parsed.content === 'string') out.lineCount = parsed.content.split('\n').length
    if (parsed.truncated) out.truncated = true
    return out
  }

  if (toolName === 'codebase_list_directory') {
    if (!Array.isArray(parsed.entries)) return undefined
    return { entryCount: parsed.entries.length, truncated: Boolean(parsed.truncated) }
  }

  return undefined
}
