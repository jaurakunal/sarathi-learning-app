import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Chat } from './Chat'

Element.prototype.scrollIntoView = vi.fn()

vi.mock('../auth/cognito', () => ({
  getIdToken: vi.fn().mockResolvedValue('mock-token'),
  getSession: vi.fn().mockResolvedValue({ isValid: () => true }),
  login: vi.fn(),
  logout: vi.fn(),
  getCurrentUser: vi.fn(),
}))

vi.mock('../api/chat', () => ({
  sendMessage: vi.fn(),
  getChatHistory: vi.fn(),
}))

vi.mock('../api/feed', () => ({
  getCard: vi.fn(),
}))

import { sendMessage, getChatHistory } from '../api/chat'
import { getCard } from '../api/feed'

const mockSendMessage = vi.mocked(sendMessage)
const mockGetChatHistory = vi.mocked(getChatHistory)
const mockGetCard = vi.mocked(getCard)

function renderChat(paperId = '2304.03442') {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[{ pathname: `/card/${paperId}/chat`, state: { paper_id: paperId } }]}>
        <Routes>
          <Route path="/card/:id/chat" element={<Chat />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('Chat page', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    mockGetChatHistory.mockResolvedValue({ turns: [], conv_id: null })
    mockGetCard.mockResolvedValue({ paper_id: '2304.03442' } as never)
  })

  it('renders empty state with prompt', async () => {
    renderChat()
    await waitFor(() => {
      expect(screen.getByText('Ask anything about this paper.')).toBeInTheDocument()
    })
  })

  it('renders back button', () => {
    renderChat()
    expect(screen.getByText('Back to paper')).toBeInTheDocument()
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
    fireEvent.click(screen.getByRole('button', { name: '' }))

    await waitFor(() => {
      expect(screen.getByText('What is reflection?')).toBeInTheDocument()
    })
  })

  it('displays response from API', async () => {
    mockSendMessage.mockResolvedValue({ conv_id: 'p1', turn_seq: 1, response: 'Reflection is the process...' })

    renderChat()
    const input = screen.getByPlaceholderText('Ask about this paper...')
    fireEvent.change(input, { target: { value: 'What is reflection?' } })
    fireEvent.click(screen.getByRole('button', { name: '' }))

    await waitFor(() => {
      expect(screen.getByText('Reflection is the process...')).toBeInTheDocument()
    })
  })

  it('shows error on failure', async () => {
    mockSendMessage.mockRejectedValue(new Error('LLM call failed'))

    renderChat()
    const input = screen.getByPlaceholderText('Ask about this paper...')
    fireEvent.change(input, { target: { value: 'Test' } })
    fireEvent.click(screen.getByRole('button', { name: '' }))

    await waitFor(() => {
      expect(screen.getByText('LLM call failed')).toBeInTheDocument()
    })
  })

  it('disables input while loading', async () => {
    mockSendMessage.mockReturnValue(new Promise(() => {}))

    renderChat()
    const input = screen.getByPlaceholderText('Ask about this paper...')
    fireEvent.change(input, { target: { value: 'Test' } })
    fireEvent.click(screen.getByRole('button', { name: '' }))

    await waitFor(() => {
      expect(input).toBeDisabled()
    })
  })

  it('shows loading indicator while waiting', async () => {
    mockSendMessage.mockReturnValue(new Promise(() => {}))

    renderChat()
    const input = screen.getByPlaceholderText('Ask about this paper...')
    fireEvent.change(input, { target: { value: 'Test' } })
    fireEvent.click(screen.getByRole('button', { name: '' }))

    await waitFor(() => {
      expect(document.querySelector('.animate-pulse')).toBeInTheDocument()
    })
  })
})
