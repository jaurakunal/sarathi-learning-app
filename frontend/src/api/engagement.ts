import { apiFetch } from './client'

export interface EngagementEvent {
  paper_id?: string
  card_id?: string
  action: 'view' | 'expand' | 'read' | 'dismiss' | 'restore' | 'bookmark' | 'ask' | 'rate' | 'impression' | 'source_click' | 'tag' | 'pin' | 'unpin'
  active_ms?: number
  scroll_depth_pct?: number
  interactions?: number
  section?: string
  rating?: number
  relevance?: string
  tags?: string[]
  seq?: number
  pin_note?: string
}

export function postEngagement(event: EngagementEvent): Promise<void> {
  return apiFetch('/engagement', {
    method: 'POST',
    body: JSON.stringify(event),
  })
}
