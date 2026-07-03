import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { MarkdownContent } from '../MarkdownContent'
import { StreamingScrambleText } from '../StreamingScrambleText'

function mockMatchMedia(reduced: boolean) {
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: reduced && query.includes('prefers-reduced-motion'),
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }))
}

function mockAnimationFrame() {
  let frameTime = 0
  vi.spyOn(performance, 'now').mockImplementation(() => frameTime)
  vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
    return window.setTimeout(() => {
      frameTime += 16
      cb(frameTime)
    }, 16)
  })
  vi.stubGlobal('cancelAnimationFrame', (id: number) => {
    window.clearTimeout(id)
  })
}

describe('StreamingScrambleText', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    mockMatchMedia(false)
    mockAnimationFrame()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('eventually resolves appended text to the real string', async () => {
    const { container, rerender } = render(
      <StreamingScrambleText text="hello" active durationMs={20} />,
    )

    expect(container.textContent).toBe('hello')

    rerender(<StreamingScrambleText text="hello world" active durationMs={20} />)

    expect(container.textContent?.startsWith('hello')).toBe(true)

    await act(async () => {
      vi.advanceTimersByTime(200)
    })

    expect(container.textContent).toBe('hello world')
  })

  it('renders plain text when reduced motion is enabled', () => {
    vi.unstubAllGlobals()
    mockMatchMedia(true)
    mockAnimationFrame()

    render(<StreamingScrambleText text="lorem ipsum" active durationMs={40} />)

    expect(screen.getByText('lorem ipsum')).toBeTruthy()
  })
})

describe('MarkdownContent streaming', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    mockMatchMedia(false)
    mockAnimationFrame()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('keeps code blocks as real markdown text', async () => {
    const content = 'Streaming paragraph.\n\n```ts\nconst x = 1\n```'

    const { container } = render(<MarkdownContent streaming>{content}</MarkdownContent>)

    expect(screen.getByText('const x = 1')).toBeTruthy()

    await act(async () => {
      vi.advanceTimersByTime(200)
    })

    expect(container.textContent).toContain('Streaming paragraph.')
    expect(container.textContent).toContain('const x = 1')
  })
})
