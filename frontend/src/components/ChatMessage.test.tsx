import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ChatMessage } from './ChatMessage'

describe('ChatMessage', () => {
  it('renders user message with correct styling', () => {
    render(<ChatMessage message={{ role: 'user', content: 'Hello!' }} />)
    expect(screen.getByText('Hello!')).toBeInTheDocument()
    const bubble = screen.getByText('Hello!').closest('div[class*="bg-zinc"]')
    expect(bubble?.className).toContain('bg-zinc-700')
  })

  it('renders assistant message with correct styling', () => {
    render(<ChatMessage message={{ role: 'assistant', content: 'Hi there.' }} />)
    expect(screen.getByText('Hi there.')).toBeInTheDocument()
    const bubble = screen.getByText('Hi there.').closest('div[class*="bg-zinc"]')
    expect(bubble?.className).toContain('bg-zinc-900')
  })

  it('shows streaming cursor when streaming', () => {
    const { container } = render(
      <ChatMessage message={{ role: 'assistant', content: 'typing', streaming: true }} />,
    )
    expect(container.querySelector('.animate-pulse')).toBeInTheDocument()
  })

  it('hides streaming cursor when not streaming', () => {
    const { container } = render(
      <ChatMessage message={{ role: 'assistant', content: 'done' }} />,
    )
    expect(container.querySelector('.animate-pulse')).not.toBeInTheDocument()
  })
})
