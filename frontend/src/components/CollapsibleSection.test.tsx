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

  it('is collapsed by default', () => {
    render(
      <CollapsibleSection title="Deep Dive">
        <p>Hidden content</p>
      </CollapsibleSection>,
    )
    const content = screen.getByText('Hidden content').parentElement
    expect(content).toHaveClass('max-h-0')
  })

  it('opens when defaultOpen is true', () => {
    render(
      <CollapsibleSection title="Gist" defaultOpen>
        <p>Visible content</p>
      </CollapsibleSection>,
    )
    const content = screen.getByText('Visible content').parentElement
    expect(content).toHaveClass('max-h-[2000px]')
  })

  it('toggles on click', () => {
    render(
      <CollapsibleSection title="Test">
        <p>Toggle me</p>
      </CollapsibleSection>,
    )
    const button = screen.getByRole('button')
    expect(screen.getByText('+'))

    fireEvent.click(button)
    expect(screen.getByText('Toggle me').parentElement).toHaveClass('max-h-[2000px]')
    expect(screen.getByText('−'))

    fireEvent.click(button)
    expect(screen.getByText('Toggle me').parentElement).toHaveClass('max-h-0')
  })
})
