import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { Chat } from './Chat'

Element.prototype.scrollIntoView = vi.fn()

vi.mock('../api/chat', () => ({
  sendMessage: vi.fn(),
}))

import { sendMessage } from '../api/chat'

const mockSendMessage = vi.mocked(sendMessage)

function renderChat(paperId = '2304.03442') {
  return render(
    <MemoryRouter initialEntries={[`/card/${paperId}/chat`]}>
      <Routes>
        <Route path="/card/:id/chat" element={<Chat />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('Chat page', () => {
  beforeEach(() => vi.resetAllMocks())

  it('renders empty state with prompt', () => {
    renderChat()
    expect(screen.getByText('Ask anything about this paper.')).toBeInTheDocument()
  })

  it('renders back button', () => {
    renderChat()
    expect(screen.getByText('← Back to paper')).toBeInTheDocument()
  })

  it('renders input field', () => {
    renderChat()
    expect(screen.getByPlaceholderText('Ask about this paper...')).toBeInTheDocument()
  })

  it('adds user message on send', async () => {
    mockSendMessage.mockResolvedValue({ conv_id: 'p1', turn_seq: 1, response: 'Answer' })

    renderChat()
    const input = screen.getByPlaceholderText('Ask about this paper...')
    fireEvent.change(input, { target: { value: 'What is reflection?' } })
    fireEvent.click(screen.getByText('→'))

    await waitFor(() => {
      expect(screen.getByText('What is reflection?')).toBeInTheDocument()
    })
  })

  it('displays response from API', async () => {
    mockSendMessage.mockResolvedValue({ conv_id: 'p1', turn_seq: 1, response: 'Reflection is the process...' })

    renderChat()
    const input = screen.getByPlaceholderText('Ask about this paper...')
    fireEvent.change(input, { target: { value: 'What is reflection?' } })
    fireEvent.click(screen.getByText('→'))

    await waitFor(() => {
      expect(screen.getByText('Reflection is the process...')).toBeInTheDocument()
    })
  })

  it('shows error on failure', async () => {
    mockSendMessage.mockRejectedValue(new Error('LLM call failed'))

    renderChat()
    const input = screen.getByPlaceholderText('Ask about this paper...')
    fireEvent.change(input, { target: { value: 'Test' } })
    fireEvent.click(screen.getByText('→'))

    await waitFor(() => {
      expect(screen.getByText('LLM call failed')).toBeInTheDocument()
    })
  })

  it('disables input while loading', async () => {
    mockSendMessage.mockReturnValue(new Promise(() => {}))

    renderChat()
    const input = screen.getByPlaceholderText('Ask about this paper...')
    fireEvent.change(input, { target: { value: 'Test' } })
    fireEvent.click(screen.getByText('→'))

    await waitFor(() => {
      expect(input).toBeDisabled()
    })
  })

  it('shows loading indicator while waiting', async () => {
    mockSendMessage.mockReturnValue(new Promise(() => {}))

    renderChat()
    const input = screen.getByPlaceholderText('Ask about this paper...')
    fireEvent.change(input, { target: { value: 'Test' } })
    fireEvent.click(screen.getByText('→'))

    await waitFor(() => {
      expect(document.querySelector('.animate-pulse')).toBeInTheDocument()
    })
  })
})
