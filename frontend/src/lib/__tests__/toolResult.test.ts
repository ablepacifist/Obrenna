import { describe, expect, it } from 'vitest'

import { summarizeToolResult } from '../toolResult'

/**
 * The live card and the reloaded card must agree.
 *
 * This shaping mirrors `_render_result_for_block` in
 * backend/app/routers/chat.py. Before it existed the live path stored
 * `resultStr.slice(0, 140)` — a truncated blob of raw JSON — and the persisted
 * path stored only an error message, so a command's output was invisible in
 * both views.
 */

describe('summarizeToolResult: run_command', () => {
  const run = (over: Record<string, unknown> = {}) =>
    summarizeToolResult('codebase_run_command', JSON.stringify({
      command: 'Rscript -e "1+1"', cwd: '.', exit_code: 0,
      stdout: 'ok', stderr: '', timed_out: false, ...over,
    }))

  it('carries the exit code and streams', () => {
    expect(run()).toMatchObject({ exitCode: 0, stdout: 'ok' })
  })

  it('keeps stderr on failure', () => {
    expect(run({ exit_code: 1, stderr: 'boom' })).toMatchObject({ exitCode: 1, stderr: 'boom' })
  })

  it('keeps the END of a long log, where the error is', () => {
    const shaped = run({ stdout: 'x'.repeat(9000) + 'FINAL ERROR' })
    expect(shaped?.stdout).toContain('FINAL ERROR')
    expect(shaped?.stdout).toContain('earlier output trimmed')
  })

  it('flags a timeout', () => {
    expect(run({ timed_out: true, exit_code: null })).toMatchObject({ timedOut: true })
  })

  it('omits empty streams rather than rendering blank panes', () => {
    const shaped = run({ stdout: '', stderr: '' })
    expect(shaped).not.toHaveProperty('stdout')
    expect(shaped).not.toHaveProperty('stderr')
  })
})

describe('summarizeToolResult: search', () => {
  const search = (matches: unknown[], extra: Record<string, unknown> = {}) =>
    summarizeToolResult('codebase_search', JSON.stringify({ matches, ...extra }))

  it('counts matches and lists distinct files', () => {
    const shaped = search([
      { path: 'shared/db_helpers.R', line_number: 4, line: 'get_db_connection <- function() {' },
      { path: 'shared/db_helpers.R', line_number: 9, line: '  get_db_connection()' },
      { path: 'app.R', line_number: 2, line: 'conn <- get_db_connection()' },
    ])
    expect(shaped?.matchCount).toBe(3)
    expect(shaped?.paths).toEqual(['shared/db_helpers.R', 'app.R'])
  })

  it('reports an honest zero rather than nothing', () => {
    expect(search([])).toMatchObject({ matchCount: 0, paths: [] })
  })

  it('caps the path list without losing the count', () => {
    const shaped = search(Array.from({ length: 40 }, (_, i) => ({ path: `f${i}.R` })))
    expect(shaped?.matchCount).toBe(40)
    expect(shaped?.paths?.length).toBe(8)
  })

  it('passes the truncation flag through', () => {
    expect(search([{ path: 'a.R' }], { truncated: true })?.truncated).toBe(true)
  })
})

describe('summarizeToolResult: reads and listings', () => {
  it('counts the lines returned', () => {
    const shaped = summarizeToolResult('codebase_read_file', JSON.stringify({
      path: 'shared/db_helpers.R', content: '1\tlibrary(DBI)\n2\tget_db_connection <- function() {',
    }))
    expect(shaped).toMatchObject({ path: 'shared/db_helpers.R', lineCount: 2 })
  })

  it('counts directory entries', () => {
    const shaped = summarizeToolResult('codebase_list_directory', JSON.stringify({
      entries: [{ name: 'a' }, { name: 'b' }], truncated: false,
    }))
    expect(shaped).toMatchObject({ entryCount: 2, truncated: false })
  })
})

describe('summarizeToolResult: bad input never breaks the card', () => {
  it('returns undefined for non-JSON', () => {
    expect(summarizeToolResult('codebase_run_command', 'Tool error: boom')).toBeUndefined()
  })

  it('returns undefined for an empty result', () => {
    expect(summarizeToolResult('codebase_search', '')).toBeUndefined()
  })

  it('returns undefined for a JSON array', () => {
    expect(summarizeToolResult('codebase_search', '[1,2,3]')).toBeUndefined()
  })

  it('returns undefined for a tool with no shaping', () => {
    expect(summarizeToolResult('web_search', '{"results":[]}')).toBeUndefined()
  })
})
