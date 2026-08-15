import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { ToolCallCard } from '../ToolCallCard'
import type { MessageBlock } from '../../../lib/api'

type ToolBlock = Extract<MessageBlock, { kind: 'tool' }>

/**
 * What the user actually sees a coding agent do.
 *
 * The reported symptom was a transcript of bare labels: `codebase_search`,
 * `codebase_run_command`, with no arguments and no results under them. Two
 * causes met here — the read-only tools had no renderer at all (`default:
 * return null` plus an args disclosure that vanished when args were empty), and
 * a command's exit code and output were never carried on the block, so the card
 * could show that a command ran but never what it printed.
 */

function block(over: Partial<ToolBlock> = {}): ToolBlock {
  return {
    kind: 'tool',
    callId: 'c1',
    toolName: 'codebase_search',
    args: {},
    status: 'done',
    ...over,
  } as ToolBlock
}

describe('ToolCallCard: run_command shows its output', () => {
  it('shows stdout and the exit code, not just the command', () => {
    render(<ToolCallCard block={block({
      toolName: 'codebase_run_command',
      args: { command: 'Rscript -e "dbListTables(con)"' },
      result: { exitCode: 0, stdout: 'loc_catchbasin\nbreeding_sites' },
    })} />)

    expect(screen.getByText(/dbListTables/)).toBeTruthy()
    expect(screen.getByText(/loc_catchbasin/)).toBeTruthy()
    expect(screen.getByText('exit 0')).toBeTruthy()
  })

  it('surfaces stderr on a failure', () => {
    render(<ToolCallCard block={block({
      toolName: 'codebase_run_command',
      args: { command: 'Rscript bad.R' },
      result: { exitCode: 1, stderr: 'could not connect to server' },
    })} />)

    expect(screen.getByText(/could not connect to server/)).toBeTruthy()
    expect(screen.getByText('exit 1')).toBeTruthy()
  })

  it('says so when the command timed out', () => {
    render(<ToolCallCard block={block({
      toolName: 'codebase_run_command',
      args: { command: 'python train.py' },
      result: { exitCode: null, timedOut: true, stdout: 'epoch 1' },
    })} />)
    expect(screen.getByText('timed out')).toBeTruthy()
  })

  it('still renders the command while it is running', () => {
    render(<ToolCallCard block={block({
      toolName: 'codebase_run_command',
      args: { command: 'npm test' },
      status: 'running',
    })} />)
    expect(screen.getByText(/npm test/)).toBeTruthy()
  })
})

describe('ToolCallCard: search is legible', () => {
  it('shows the pattern and where it was found', () => {
    render(<ToolCallCard block={block({
      args: { pattern: 'get_db_connection' },
      result: { matchCount: 2, paths: ['shared/db_helpers.R', 'app.R'] },
    })} />)

    expect(screen.getByText(/get_db_connection/)).toBeTruthy()
    expect(screen.getByText('2 matches')).toBeTruthy()
    expect(screen.getByText('shared/db_helpers.R')).toBeTruthy()
  })

  it('says plainly when nothing matched', () => {
    render(<ToolCallCard block={block({
      args: { pattern: 'nope' },
      result: { matchCount: 0, paths: [] },
    })} />)
    expect(screen.getByText('no matches')).toBeTruthy()
  })

  it('marks a capped result so the count is not read as complete', () => {
    render(<ToolCallCard block={block({
      args: { pattern: 'x' },
      result: { matchCount: 100, paths: ['a.R'], truncated: true },
    })} />)
    expect(screen.getByText('100 matches (capped)')).toBeTruthy()
  })

  it('is not a bare label when only the pattern is known', () => {
    const { container } = render(<ToolCallCard block={block({ args: { pattern: 'get_db_connection' } })} />)
    expect(container.textContent).toContain('get_db_connection')
  })
})

describe('ToolCallCard: reads and listings', () => {
  it('names the file read and how much of it came back', () => {
    render(<ToolCallCard block={block({
      toolName: 'codebase_read_file',
      args: { path: 'shared/db_helpers.R' },
      result: { path: 'shared/db_helpers.R', lineCount: 42 },
    })} />)
    expect(screen.getByText(/shared\/db_helpers\.R/)).toBeTruthy()
    expect(screen.getByText(/42 lines/)).toBeTruthy()
  })

  it('shows how many entries a listing returned', () => {
    render(<ToolCallCard block={block({
      toolName: 'codebase_list_directory',
      args: { path: 'shared' },
      result: { entryCount: 7 },
    })} />)
    expect(screen.getByText(/7 entries/)).toBeTruthy()
  })
})

describe('ToolCallCard: the card is never empty', () => {
  it('falls back to a running headline before narration lands', () => {
    render(<ToolCallCard block={block({ toolName: 'codebase_search', status: 'running' })} />)
    expect(screen.getByText(/Running codebase_search/)).toBeTruthy()
  })

  it('shows the narration headline when there is one', () => {
    render(<ToolCallCard block={block({ description: 'Searching the codebase for the DB helper' })} />)
    expect(screen.getByText('Searching the codebase for the DB helper')).toBeTruthy()
  })

  it('marks an errored call', () => {
    render(<ToolCallCard block={block({ status: 'error' })} />)
    expect(screen.getByText('error')).toBeTruthy()
  })
})

describe('ToolCallCard: existing write rendering still works', () => {
  it('draws a diff for an edit', () => {
    render(<ToolCallCard block={block({
      toolName: 'codebase_edit_file',
      args: { path: 'a.R', old_string: 'old line', new_string: 'new line' },
    })} />)
    expect(screen.getByText(/- old line/)).toBeTruthy()
    expect(screen.getByText(/\+ new line/)).toBeTruthy()
  })
})
