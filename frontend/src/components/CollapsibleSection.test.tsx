import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { CollapsibleSection } from './CollapsibleSection'

describe('CollapsibleSection', () => {
  it('renders title', () => {
    render(
      <CollapsibleSection title="Gist">
        <p>Content here</p>
      </CollapsibleSection>,
    )
    expect(screen.getByText('Gist')).toBeInTheDocument()
  })

  it('is collapsed by default (content not in DOM)', () => {
    render(
      <CollapsibleSection title="Deep Dive">
        <p>Hidden content</p>
      </CollapsibleSection>,
    )
    expect(screen.queryByText('Hidden content')).not.toBeInTheDocument()
  })

  it('opens when defaultOpen is true', () => {
    render(
      <CollapsibleSection title="Gist" defaultOpen>
        <p>Visible content</p>
      </CollapsibleSection>,
    )
    expect(screen.getByText('Visible content')).toBeInTheDocument()
  })

  it('toggles on click — opens to show content', () => {
    render(
      <CollapsibleSection title="Test">
        <p>Toggle me</p>
      </CollapsibleSection>,
    )
    const button = screen.getByRole('button')

    // Initially collapsed — content not in DOM
    expect(screen.queryByText('Toggle me')).not.toBeInTheDocument()

    // Click to open
    fireEvent.click(button)
    expect(screen.getByText('Toggle me')).toBeInTheDocument()
  })
})
