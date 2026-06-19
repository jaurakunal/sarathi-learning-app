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

// Mock AppSync client
const mockGraphql = vi.fn()
vi.mock('../api/appsync', () => ({
  client: { graphql: (...args: unknown[]) => mockGraphql(...args) },
  SEND_MESSAGE: 'mock-send-mutation',
  ON_CHUNK: 'mock-on-chunk-subscription',
}))

import { getChatHistory } from '../api/chat'
import { getCard } from '../api/feed'

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
    // Mock subscription (returns object with subscribe method)
    mockGraphql.mockImplementation((opts: any) => {
      if (opts.query === 'mock-on-chunk-subscription') {
        return { subscribe: vi.fn() }
      }
      // sendMessage mutation
      return Promise.resolve({ data: { sendMessage: { conversationId: 'p1', turnSeq: 1, status: 'ok' } } })
    })

    renderChat()
    const input = screen.getByPlaceholderText('Ask about this paper...')
    fireEvent.change(input, { target: { value: 'What is reflection?' } })
    fireEvent.click(screen.getByRole('button', { name: '' }))

    await waitFor(() => {
      expect(screen.getByText('What is reflection?')).toBeInTheDocument()
    })
  })

  it('shows error on mutation failure', async () => {
    mockGraphql.mockImplementation((opts: any) => {
      if (opts.query === 'mock-on-chunk-subscription') {
        return { subscribe: vi.fn() }
      }
      return Promise.resolve({ data: { sendMessage: { conversationId: 'p1', turnSeq: 1, status: 'error:llm_failed' } } })
    })

    renderChat()
    const input = screen.getByPlaceholderText('Ask about this paper...')
    fireEvent.change(input, { target: { value: 'Test' } })
    fireEvent.click(screen.getByRole('button', { name: '' }))

    await waitFor(() => {
      expect(screen.getByText('llm_failed')).toBeInTheDocument()
    })
  })

  it('disables input while loading', async () => {
    // Subscription setup, mutation never resolves
    mockGraphql.mockImplementation((opts: any) => {
      if (opts.query === 'mock-on-chunk-subscription') {
        return { subscribe: vi.fn() }
      }
      return new Promise(() => {})
    })

    renderChat()
    const input = screen.getByPlaceholderText('Ask about this paper...')
    fireEvent.change(input, { target: { value: 'Test' } })
    fireEvent.click(screen.getByRole('button', { name: '' }))

    await waitFor(() => {
      expect(input).toBeDisabled()
    })
  })

  it('loads conversation history on mount', async () => {
    mockGetChatHistory.mockResolvedValue({
      turns: [
        { seq: 1, request: 'Old question', response: 'Old answer', request_ts: '', response_ts: '' },
      ],
      conv_id: '2304.03442',
    })

    renderChat()

    await waitFor(() => {
      expect(screen.getByText('Old question')).toBeInTheDocument()
      expect(screen.getByText('Old answer')).toBeInTheDocument()
    })
  })

  it('shows loading indicator while waiting for stream', async () => {
    mockGraphql.mockImplementation((opts: any) => {
      if (opts.query === 'mock-on-chunk-subscription') {
        return { subscribe: vi.fn() }
      }
      return new Promise(() => {})
    })

    renderChat()
    const input = screen.getByPlaceholderText('Ask about this paper...')
    fireEvent.change(input, { target: { value: 'Test' } })
    fireEvent.click(screen.getByRole('button', { name: '' }))

    await waitFor(() => {
      // ChatLoading uses animated spans — look for the container
      expect(screen.getByText('∞')).toBeInTheDocument()
    })
  })

  it('creates a subscription for each message sent', async () => {
    let subscribeCount = 0

    mockGraphql.mockImplementation((opts: any) => {
      if (opts.query === 'mock-on-chunk-subscription') {
        subscribeCount++
        return { subscribe: () => ({ unsubscribe: vi.fn() }) }
      }
      return Promise.resolve({ data: { sendMessage: { conversationId: 'p1', turnSeq: subscribeCount, status: 'ok' } } })
    })

    renderChat()
    const input = screen.getByPlaceholderText('Ask about this paper...')

    // Send first message
    fireEvent.change(input, { target: { value: 'First' } })
    fireEvent.click(screen.getByRole('button', { name: '' }))

    await waitFor(() => {
      expect(screen.getByText('First')).toBeInTheDocument()
    })

    // Verify subscription was created
    expect(subscribeCount).toBe(1)
  })

  it('does not duplicate chunks when subscription fires once per chunk', async () => {
    let chunkHandler: ((data: any) => void) | null = null

    mockGraphql.mockImplementation((opts: any) => {
      if (opts.query === 'mock-on-chunk-subscription') {
        return {
          subscribe: (handlers: any) => {
            chunkHandler = (data: any) => handlers.next({ data })
            return { unsubscribe: vi.fn() }
          },
        }
      }
      return Promise.resolve({ data: { sendMessage: { conversationId: 'p1', turnSeq: 1, status: 'ok' } } })
    })

    mockGetChatHistory.mockResolvedValue({ turns: [{ seq: 1, request: 'Test', response: 'Hello world', request_ts: '', response_ts: '' }], conv_id: 'p1' })

    renderChat()
    const input = screen.getByPlaceholderText('Ask about this paper...')
    fireEvent.change(input, { target: { value: 'Test' } })
    fireEvent.click(screen.getByRole('button', { name: '' }))

    await waitFor(() => expect(chunkHandler).not.toBeNull())

    // Simulate chunks arriving one at a time
    chunkHandler!({ onChunk: { conversationId: 'p1', turnSeq: 1, chunk: 'Hello ', done: false } })
    chunkHandler!({ onChunk: { conversationId: 'p1', turnSeq: 1, chunk: 'world', done: false } })
    chunkHandler!({ onChunk: { conversationId: 'p1', turnSeq: 1, chunk: '', done: true, tokensIn: 100, tokensOut: 5 } })

    // After done + history fetch, the final text should be "Hello world" (no duplication)
    await waitFor(() => {
      expect(screen.getByText('Hello world')).toBeInTheDocument()
    })

    // Verify NO duplicated text like "Hello Hello world world"
    const assistantMessages = screen.getAllByText(/Hello/)
    expect(assistantMessages.length).toBe(1)
  })
})
