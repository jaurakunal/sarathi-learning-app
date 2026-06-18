import { describe, it, expect, vi, beforeEach } from 'vitest'
import { getFeed, getCard } from './feed'
import { mockFeedResponse, mockCardDetail } from '../test/mocks'

vi.mock('./client', () => ({
  apiFetch: vi.fn(),
}))

import { apiFetch } from './client'

const mockApiFetch = vi.mocked(apiFetch)

describe('getFeed', () => {
  beforeEach(() => vi.resetAllMocks())

  it('calls /feed with default limit', async () => {
    mockApiFetch.mockResolvedValue(mockFeedResponse)

    const result = await getFeed()

    expect(mockApiFetch).toHaveBeenCalledWith('/feed?limit=20')
    expect(result).toEqual(mockFeedResponse)
  })

  it('passes custom limit', async () => {
    mockApiFetch.mockResolvedValue(mockFeedResponse)

    await getFeed(null, 5)

    expect(mockApiFetch).toHaveBeenCalledWith('/feed?limit=5')
  })

  it('passes lastKey for pagination', async () => {
    mockApiFetch.mockResolvedValue(mockFeedResponse)
    const lastKey = { PK: 'USER#x#FEED', SK: 'CARD#123' }

    await getFeed(lastKey)

    const call = mockApiFetch.mock.calls[0][0] as string
    expect(call).toContain('lastKey=')
    expect(call).toContain(encodeURIComponent(JSON.stringify(lastKey)))
  })
})

describe('getCard', () => {
  beforeEach(() => vi.resetAllMocks())

  it('calls /feed/{cardId}', async () => {
    mockApiFetch.mockResolvedValue(mockCardDetail)

    const result = await getCard('20260615_023000_abc123')

    expect(mockApiFetch).toHaveBeenCalledWith('/feed/20260615_023000_abc123')
    expect(result).toEqual(mockCardDetail)
  })

  it('encodes special characters in card ID', async () => {
    mockApiFetch.mockResolvedValue(mockCardDetail)

    await getCard('card with spaces')

    expect(mockApiFetch).toHaveBeenCalledWith('/feed/card%20with%20spaces')
  })
})
