import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ChatMessage } from './ChatMessage'

describe('ChatMessage', () => {
  it('renders user message with correct styling', () => {
    render(<ChatMessage message={{ role: 'user', content: 'Hello!' }} />)
    expect(screen.getByText('Hello!')).toBeInTheDocument()
    const bubble = screen.getByText('Hello!').closest('div[class*="bg-accent"]')
    expect(bubble?.className).toContain('bg-accent/20')
  })

  it('renders assistant message with correct styling', () => {
    render(<ChatMessage message={{ role: 'assistant', content: 'Hi there.' }} />)
    expect(screen.getByText('Hi there.')).toBeInTheDocument()
    const bubble = screen.getByText('Hi there.').closest('div[class*="glass-card"]')
    expect(bubble?.className).toContain('glass-card')
  })

  it('shows streaming indicator when streaming', () => {
    render(
      <ChatMessage message={{ role: 'assistant', content: 'typing', streaming: true }} />,
    )
    expect(screen.getByTestId('streaming-indicator')).toBeInTheDocument()
  })

  it('hides streaming indicator when not streaming', () => {
    render(
      <ChatMessage message={{ role: 'assistant', content: 'done' }} />,
    )
    expect(screen.queryByTestId('streaming-indicator')).not.toBeInTheDocument()
  })
})
