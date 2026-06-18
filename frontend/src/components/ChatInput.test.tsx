import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { ChatInput } from './ChatInput'

describe('ChatInput', () => {
  it('renders textarea and send button', () => {
    render(<ChatInput onSend={vi.fn()} />)
    expect(screen.getByPlaceholderText('Ask about this paper...')).toBeInTheDocument()
    expect(screen.getByText('→')).toBeInTheDocument()
  })

  it('calls onSend with trimmed text on submit', () => {
    const onSend = vi.fn()
    render(<ChatInput onSend={onSend} />)
    const input = screen.getByPlaceholderText('Ask about this paper...')
    fireEvent.change(input, { target: { value: '  Hello world  ' } })
    fireEvent.click(screen.getByText('→'))
    expect(onSend).toHaveBeenCalledWith('Hello world')
  })

  it('clears input after send', () => {
    render(<ChatInput onSend={vi.fn()} />)
    const input = screen.getByPlaceholderText('Ask about this paper...') as HTMLTextAreaElement
    fireEvent.change(input, { target: { value: 'Test' } })
    fireEvent.click(screen.getByText('→'))
    expect(input.value).toBe('')
  })

  it('does not send empty messages', () => {
    const onSend = vi.fn()
    render(<ChatInput onSend={onSend} />)
    fireEvent.click(screen.getByText('→'))
    expect(onSend).not.toHaveBeenCalled()
  })

  it('disables input when disabled prop is true', () => {
    render(<ChatInput onSend={vi.fn()} disabled />)
    const input = screen.getByPlaceholderText('Ask about this paper...')
    expect(input).toBeDisabled()
  })

  it('sends on Enter key', () => {
    const onSend = vi.fn()
    render(<ChatInput onSend={onSend} />)
    const input = screen.getByPlaceholderText('Ask about this paper...')
    fireEvent.change(input, { target: { value: 'Test' } })
    fireEvent.keyDown(input, { key: 'Enter', shiftKey: false })
    expect(onSend).toHaveBeenCalledWith('Test')
  })

  it('does not send on Shift+Enter', () => {
    const onSend = vi.fn()
    render(<ChatInput onSend={onSend} />)
    const input = screen.getByPlaceholderText('Ask about this paper...')
    fireEvent.change(input, { target: { value: 'Test' } })
    fireEvent.keyDown(input, { key: 'Enter', shiftKey: true })
    expect(onSend).not.toHaveBeenCalled()
  })
})
