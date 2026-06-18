import { apiFetch } from './client'

export interface EngagementEvent {
  paper_id: string
  card_id: string
  action: 'view' | 'expand' | 'read' | 'dismiss' | 'bookmark' | 'ask'
  active_ms?: number
  scroll_depth_pct?: number
  interactions?: number
  section?: string
}

export function postEngagement(event: EngagementEvent): Promise<void> {
  return apiFetch('/engagement', {
    method: 'POST',
    body: JSON.stringify(event),
  })
}
