import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Feed } from './Feed'
import { mockFeedResponse } from '../test/mocks'

vi.mock('../api/feed', () => ({
  getFeed: vi.fn(),
}))

vi.mock('../auth/cognito', () => ({
  logout: vi.fn(),
}))

import { getFeed } from '../api/feed'

const mockGetFeed = vi.mocked(getFeed)

function renderFeed() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <Feed />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('Feed page', () => {
  beforeEach(() => vi.resetAllMocks())

  it('shows loading state initially', () => {
    mockGetFeed.mockReturnValue(new Promise(() => {}))
    renderFeed()
    expect(document.querySelector('.animate-spin')).toBeInTheDocument()
  })

  it('renders cards on success', async () => {
    mockGetFeed.mockResolvedValue(mockFeedResponse)
    renderFeed()

    await waitFor(() => {
      expect(screen.getByText(/You built this cold two years ago/)).toBeInTheDocument()
    })
  })

  it('shows empty state when no cards', async () => {
    mockGetFeed.mockResolvedValue({ cards: [], lastKey: null })
    renderFeed()

    await waitFor(() => {
      expect(screen.getByText(/No cards yet/)).toBeInTheDocument()
    })
  })

  it('shows error state on failure', async () => {
    mockGetFeed.mockRejectedValue(new Error('Network error'))
    renderFeed()

    await waitFor(() => {
      expect(screen.getByText('Network error')).toBeInTheDocument()
    })
  })

  it('renders the header', async () => {
    mockGetFeed.mockResolvedValue(mockFeedResponse)
    renderFeed()

    await waitFor(() => {
      expect(screen.getByText('Sārathi')).toBeInTheDocument()
    })
  })

  it('shows sign out button', async () => {
    mockGetFeed.mockResolvedValue(mockFeedResponse)
    renderFeed()

    await waitFor(() => {
      expect(screen.getByText('Sign out')).toBeInTheDocument()
    })
  })
})
