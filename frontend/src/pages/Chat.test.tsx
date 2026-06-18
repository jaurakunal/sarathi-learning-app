import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { Chat } from './Chat'

// jsdom doesn't implement scrollIntoView
Element.prototype.scrollIntoView = vi.fn()

vi.mock('../api/chat', () => ({
  streamChat: vi.fn(),
}))

import { streamChat } from '../api/chat'

const mockStreamChat = vi.mocked(streamChat)

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

  it('renders send button', () => {
    renderChat()
    expect(screen.getByText('→')).toBeInTheDocument()
  })

  it('adds user message on send', async () => {
    async function* fakeStream() {
      yield { type: 'start' as const, conv_id: 'conv1', turn_seq: 1 }
      yield { type: 'chunk' as const, text: 'Response text' }
      yield { type: 'done' as const, tokens_in: 100, tokens_out: 10 }
    }
    mockStreamChat.mockReturnValue(fakeStream())

    renderChat()
    const input = screen.getByPlaceholderText('Ask about this paper...')
    fireEvent.change(input, { target: { value: 'What is reflection?' } })
    fireEvent.click(screen.getByText('→'))

    await waitFor(() => {
      expect(screen.getByText('What is reflection?')).toBeInTheDocument()
    })
  })

  it('displays streamed response', async () => {
    async function* fakeStream() {
      yield { type: 'start' as const, conv_id: 'conv1', turn_seq: 1 }
      yield { type: 'chunk' as const, text: 'Reflection is ' }
      yield { type: 'chunk' as const, text: 'the process...' }
      yield { type: 'done' as const, tokens_in: 100, tokens_out: 20 }
    }
    mockStreamChat.mockReturnValue(fakeStream())

    renderChat()
    const input = screen.getByPlaceholderText('Ask about this paper...')
    fireEvent.change(input, { target: { value: 'What is reflection?' } })
    fireEvent.click(screen.getByText('→'))

    await waitFor(() => {
      expect(screen.getByText('Reflection is the process...')).toBeInTheDocument()
    })
  })

  it('shows error on stream failure', async () => {
    mockStreamChat.mockImplementation(async function* () {
      throw new Error('Network error')
    })

    renderChat()
    const input = screen.getByPlaceholderText('Ask about this paper...')
    fireEvent.change(input, { target: { value: 'Test' } })
    fireEvent.click(screen.getByText('→'))

    await waitFor(() => {
      expect(screen.getByText('Network error')).toBeInTheDocument()
    })
  })

  it('disables input while streaming', async () => {
    let resolve: () => void
    const blockingPromise = new Promise<void>((r) => { resolve = r })

    async function* slowStream() {
      yield { type: 'start' as const, conv_id: 'conv1', turn_seq: 1 }
      await blockingPromise
      yield { type: 'done' as const, tokens_in: 0, tokens_out: 0 }
    }
    mockStreamChat.mockReturnValue(slowStream())

    renderChat()
    const input = screen.getByPlaceholderText('Ask about this paper...')
    fireEvent.change(input, { target: { value: 'Test' } })
    fireEvent.click(screen.getByText('→'))

    await waitFor(() => {
      expect(input).toBeDisabled()
    })

    resolve!()
  })
})
