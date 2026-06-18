import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { CardDetail } from './CardDetail'
import { mockCardDetail } from '../test/mocks'

vi.mock('../api/feed', () => ({
  getCard: vi.fn(),
}))

vi.mock('../hooks/useEngagement', () => ({
  useEngagement: () => ({
    trackScroll: vi.fn(),
    trackInteraction: vi.fn(),
    fireEvent: vi.fn(),
    fireExpand: vi.fn(),
    fireRead: vi.fn(),
    fireDismiss: vi.fn(),
    getActiveMs: () => 0,
    scrollDepthRef: { current: 0 },
  }),
}))

import { getCard } from '../api/feed'

const mockGetCard = vi.mocked(getCard)

function renderCardDetail(cardId = '20260615_023000_abc123') {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/card/${cardId}`]}>
        <Routes>
          <Route path="/card/:id" element={<CardDetail />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('CardDetail page', () => {
  beforeEach(() => vi.resetAllMocks())

  it('shows loading state', () => {
    mockGetCard.mockReturnValue(new Promise(() => {}))
    renderCardDetail()
    expect(document.querySelector('.animate-spin')).toBeInTheDocument()
  })

  it('renders card content on success', async () => {
    mockGetCard.mockResolvedValue(mockCardDetail)
    renderCardDetail()

    await waitFor(() => {
      expect(screen.getByText(/You built this cold two years ago/)).toBeInTheDocument()
    })
    expect(screen.getByText('A one-paragraph summary of the paper.')).toBeInTheDocument()
  })

  it('renders key ideas', async () => {
    mockGetCard.mockResolvedValue(mockCardDetail)
    renderCardDetail()

    await waitFor(() => {
      expect(screen.getByText('Agents can reflect')).toBeInTheDocument()
      expect(screen.getByText('Memory streams matter')).toBeInTheDocument()
      expect(screen.getByText('Retrieval is key')).toBeInTheDocument()
    })
  })

  it('renders glossary terms after expanding section', async () => {
    mockGetCard.mockResolvedValue(mockCardDetail)
    renderCardDetail()

    await waitFor(() => {
      expect(screen.getByText('Glossary')).toBeInTheDocument()
    })

    // Glossary section is collapsed by default; click to expand
    fireEvent.click(screen.getByText('Glossary'))

    await waitFor(() => {
      expect(screen.getByText('Reflection')).toBeInTheDocument()
      expect(screen.getByText('Memory stream')).toBeInTheDocument()
    })
  })

  it('renders hypothesis relevance', async () => {
    mockGetCard.mockResolvedValue(mockCardDetail)
    renderCardDetail()

    await waitFor(() => {
      expect(screen.getByText(/Supports the bet/)).toBeInTheDocument()
    })
  })

  it('renders honesty note', async () => {
    mockGetCard.mockResolvedValue(mockCardDetail)
    renderCardDetail()

    await waitFor(() => {
      expect(screen.getByText('Landmark paper. Worth a full read.')).toBeInTheDocument()
    })
  })

  it('renders suggested questions', async () => {
    mockGetCard.mockResolvedValue(mockCardDetail)
    renderCardDetail()

    await waitFor(() => {
      expect(screen.getByText('What exactly is reflection?')).toBeInTheDocument()
      expect(screen.getByText('Could I add this to my product?')).toBeInTheDocument()
    })
  })

  it('renders source link', async () => {
    mockGetCard.mockResolvedValue(mockCardDetail)
    renderCardDetail()

    await waitFor(() => {
      const link = screen.getByText('Read full paper')
      expect(link.closest('a')).toHaveAttribute('href', 'https://arxiv.org/abs/2304.03442')
      expect(link.closest('a')).toHaveAttribute('target', '_blank')
    })
  })

  it('shows back button', async () => {
    mockGetCard.mockResolvedValue(mockCardDetail)
    renderCardDetail()

    await waitFor(() => {
      expect(screen.getByText('Back')).toBeInTheDocument()
    })
  })

  it('shows error state on failure', async () => {
    mockGetCard.mockRejectedValue(new Error('Not found'))
    renderCardDetail()

    await waitFor(() => {
      expect(screen.getByText('Card not found')).toBeInTheDocument()
    })
  })
})
