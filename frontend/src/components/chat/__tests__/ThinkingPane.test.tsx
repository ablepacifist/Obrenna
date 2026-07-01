import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { ThinkingPane } from '../ThinkingPane'

describe('ThinkingPane', () => {
  it('renders nothing when text is empty', () => {
    const { container } = render(
      <ThinkingPane text="" expanded={true} onExpandedChange={vi.fn()} />,
    )
    expect(container).toBeEmptyDOMElement()
  })

  it('renders the header and body when expanded', () => {
    render(<ThinkingPane text="reasoning here" expanded={true} onExpandedChange={vi.fn()} />)
    expect(screen.getByText('Thinking')).toBeTruthy()
    expect(screen.getByText('reasoning here')).toBeTruthy()
    expect(screen.getByText('Hide')).toBeTruthy()
  })

  it('hides the body when collapsed but keeps the header', () => {
    render(<ThinkingPane text="reasoning here" expanded={false} onExpandedChange={vi.fn()} />)
    expect(screen.getByText('Thinking')).toBeTruthy()
    expect(screen.getByText('Show')).toBeTruthy()
    expect(screen.queryByText('reasoning here')).toBeNull()
  })

  it('toggles expanded via the header button', () => {
    const onExpandedChange = vi.fn()
    render(<ThinkingPane text="reasoning here" expanded={true} onExpandedChange={onExpandedChange} />)
    fireEvent.click(screen.getByText('Hide'))
    expect(onExpandedChange).toHaveBeenCalledWith(false)
  })
})