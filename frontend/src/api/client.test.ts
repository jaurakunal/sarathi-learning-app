import { describe, it, expect, vi, beforeEach } from 'vitest'
import { apiFetch } from './client'

vi.mock('../auth/cognito', () => ({
  getIdToken: vi.fn(),
}))

import { getIdToken } from '../auth/cognito'

const mockGetIdToken = vi.mocked(getIdToken)

describe('apiFetch', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    globalThis.fetch = vi.fn()
  })

  it('attaches auth token to requests', async () => {
    mockGetIdToken.mockResolvedValue('test-jwt-token')
    const mockFetch = vi.mocked(globalThis.fetch)
    mockFetch.mockResolvedValue(new Response(JSON.stringify({ data: 'ok' }), { status: 200 }))

    await apiFetch('/feed')

    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining('/feed'),
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: 'test-jwt-token',
        }),
      }),
    )
  })

  it('throws when not authenticated', async () => {
    mockGetIdToken.mockResolvedValue(null)

    await expect(apiFetch('/feed')).rejects.toThrow('Not authenticated')
  })

  it('throws on non-ok response with error message', async () => {
    mockGetIdToken.mockResolvedValue('token')
    const mockFetch = vi.mocked(globalThis.fetch)
    mockFetch.mockResolvedValue(new Response(JSON.stringify({ error: 'Card not found' }), { status: 404 }))

    await expect(apiFetch('/feed/123')).rejects.toThrow('Card not found')
  })

  it('throws generic error when response has no body', async () => {
    mockGetIdToken.mockResolvedValue('token')
    const mockFetch = vi.mocked(globalThis.fetch)
    mockFetch.mockResolvedValue(new Response('', { status: 500 }))

    await expect(apiFetch('/feed')).rejects.toThrow('API error: 500')
  })

  it('returns parsed JSON on success', async () => {
    mockGetIdToken.mockResolvedValue('token')
    const mockFetch = vi.mocked(globalThis.fetch)
    mockFetch.mockResolvedValue(new Response(JSON.stringify({ cards: [] }), { status: 200 }))

    const result = await apiFetch('/feed')
    expect(result).toEqual({ cards: [] })
  })
})
