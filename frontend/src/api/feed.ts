import { apiFetch } from './client'
import type { FeedResponse, CardDetail } from '../types/feed'

export function getFeed(lastKey?: Record<string, unknown> | null, limit = 20): Promise<FeedResponse> {
  const params = new URLSearchParams({ limit: String(limit) })
  if (lastKey) {
    params.set('lastKey', JSON.stringify(lastKey))
  }
  return apiFetch<FeedResponse>(`/feed?${params}`)
}

export function getCard(cardId: string): Promise<CardDetail> {
  return apiFetch<CardDetail>(`/feed/${encodeURIComponent(cardId)}`)
}
