import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Profile } from './Profile'
import type { ProfileData } from '../api/profile'
import type { BriefsResponse } from '../api/briefs'

vi.mock('../api/profile', () => ({
  getProfile: vi.fn(),
}))

vi.mock('../api/briefs', () => ({
  getBriefs: vi.fn(),
}))

vi.mock('../auth/cognito', () => ({
  logout: vi.fn(),
  getIdToken: vi.fn().mockResolvedValue('fake-token'),
}))

import { getProfile } from '../api/profile'
import { getBriefs } from '../api/briefs'

const mockGetProfile = vi.mocked(getProfile)
const mockGetBriefs = vi.mocked(getBriefs)

const baseProfile: ProfileData = {
  areas: [
    { id: 'ai', name: 'AI', status: 'hot', frontier: 'edge', last_engaged: null },
  ],
  hypothesis: null,
  summaries: {
    yesterday: 'Yesterday: read 2 papers.',
    '3_day': 'Last 3 days: more reading.',
    '7_day': 'Last 7 days summary content.',
    month: 'Month summary content.',
    quarter: 'Quarter summary content.',
  },
  stats_7d: {
    papers_read: 5,
    papers_dismissed: 0,
    papers_bookmarked: 1,
    questions_asked: 2,
    source_clicks: 1,
    sections_expanded: 3,
    total_active_ms: 60000,
  },
  timeline: [],
  learning_style: null,
  latest_brief: null,
  insights: [],
}

function renderProfile() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <Profile />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('Profile page', () => {
  beforeEach(() => vi.resetAllMocks())

  it('renders all four tabs including Activity', async () => {
    mockGetProfile.mockResolvedValue(baseProfile)

    renderProfile()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /overview/i })).toBeInTheDocument()
    })
    expect(screen.getByRole('button', { name: /insights/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /timeline/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /activity/i })).toBeInTheDocument()
  })

  it('shows tiered summaries and brief archive when Activity tab is opened', async () => {
    mockGetProfile.mockResolvedValue(baseProfile)
    const briefsResponse: BriefsResponse = {
      briefs: [
        {
          week: '2026-06-30',
          content: '## Week brief\n\nThis week you read interesting papers about agents.',
          generated_at: '2026-06-30T17:00:00Z',
        },
      ],
      next_after_week: null,
    }
    mockGetBriefs.mockResolvedValue(briefsResponse)

    renderProfile()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /activity/i })).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: /activity/i }))

    // All five tier labels should render
    await waitFor(() => {
      expect(screen.getByText('Yesterday')).toBeInTheDocument()
    })
    expect(screen.getByText('Last 3 days')).toBeInTheDocument()
    expect(screen.getByText('Last 7 days')).toBeInTheDocument()
    expect(screen.getByText('Last month')).toBeInTheDocument()
    expect(screen.getByText('Last quarter')).toBeInTheDocument()

    // Brief archive renders the seeded brief
    await waitFor(() => {
      expect(screen.getByText(/Week of/i)).toBeInTheDocument()
    })
  })

  it('shows empty state when no briefs exist', async () => {
    mockGetProfile.mockResolvedValue(baseProfile)
    mockGetBriefs.mockResolvedValue({ briefs: [], next_after_week: null })

    renderProfile()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /activity/i })).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('button', { name: /activity/i }))

    await waitFor(() => {
      expect(
        screen.getByText(/No weekly briefs yet/i),
      ).toBeInTheDocument()
    })
  })

  it('shows muted text when summary is missing', async () => {
    mockGetProfile.mockResolvedValue({
      ...baseProfile,
      summaries: {
        // 7_day and month default-expanded; leave them missing to surface empty text.
        '7_day': '',
        month: 'No activity yet.',
      },
    })
    mockGetBriefs.mockResolvedValue({ briefs: [], next_after_week: null })

    renderProfile()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /activity/i })).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('button', { name: /activity/i }))

    // 7_day and month are expanded by default, so their empty messages render
    await waitFor(() => {
      const empties = screen.getAllByText(/No activity in this window/i)
      expect(empties.length).toBeGreaterThanOrEqual(2)
    })
  })
})
