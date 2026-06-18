import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MathNote } from './MathNote'

describe('MathNote', () => {
  it('renders plain text explanation', () => {
    render(<MathNote plain="Importance is scored by recency." />)
    expect(screen.getByText('Importance is scored by recency.')).toBeInTheDocument()
  })

  it('hides equation by default when provided', () => {
    render(<MathNote plain="Score formula" equation="s = r * d" />)
    expect(screen.queryByText('s = r * d')).not.toBeInTheDocument()
    expect(screen.getByText('Show equation →')).toBeInTheDocument()
  })

  it('reveals equation on tap', () => {
    render(<MathNote plain="Score formula" equation="s = r * d" />)
    fireEvent.click(screen.getByText('Show equation →'))
    expect(screen.getByText('s = r * d')).toBeInTheDocument()
  })

  it('does not show reveal button when no equation', () => {
    render(<MathNote plain="No equation here" />)
    expect(screen.queryByText('Show equation →')).not.toBeInTheDocument()
  })
})
