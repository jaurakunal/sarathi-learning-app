import { apiFetch } from './client'

export type FeedbackCategory = 'bug' | 'idea' | 'other'

export function sendFeedback(message: string, category: FeedbackCategory): Promise<{ status: string }> {
  return apiFetch<{ status: string }>('/feedback', {
    method: 'POST',
    body: JSON.stringify({ message, category }),
  })
}
