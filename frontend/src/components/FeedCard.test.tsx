import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { FeedCard } from './FeedCard'
import { mockCardSummary } from '../test/mocks'

vi.mock('../api/engagement', () => ({
  postEngagement: vi.fn().mockResolvedValue(undefined),
}))


const mockNavigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return { ...actual, useNavigate: () => mockNavigate }
})

function renderCard(props = {}) {
  return render(
    <MemoryRouter>
      <FeedCard card={{ ...mockCardSummary, ...props }} index={0} />
    </MemoryRouter>,
  )
}

describe('FeedCard', () => {
  it('renders the hook text', () => {
    renderCard()
    expect(screen.getByText(/You built this cold two years ago/)).toBeInTheDocument()
  })

  it('renders the why_you_now text', () => {
    renderCard()
    expect(screen.getByText(/formal version of your cloning/)).toBeInTheDocument()
  })

  it('renders time estimate', () => {
    renderCard()
    expect(screen.getByText('18 min')).toBeInTheDocument()
  })

  it('navigates to card detail on click', () => {
    renderCard()
    fireEvent.click(screen.getByText(/You built this cold two years ago/))
    expect(mockNavigate).toHaveBeenCalledWith('/card/20260615_023000_abc123')
  })

  it('does not show card_type badge for new_paper', () => {
    renderCard({ card_type: 'new_paper' })
    expect(screen.queryByText('new paper')).not.toBeInTheDocument()
  })

  it('shows card_type badge for non-new_paper types', () => {
    renderCard({ card_type: 'resurface' })
    expect(screen.getByText('resurface')).toBeInTheDocument()
  })

  it('handles empty why_you_now gracefully', () => {
    renderCard({ why_you_now: '' })
    expect(screen.getByText(/You built this cold/)).toBeInTheDocument()
  })
})
