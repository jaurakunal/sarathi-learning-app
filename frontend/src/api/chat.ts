import { apiFetch } from './client'

export interface ChatResponse {
  conv_id: string
  turn_seq: number
  response: string
}

export function sendMessage(paperId: string, message: string): Promise<ChatResponse> {
  return apiFetch<ChatResponse>('/chat', {
    method: 'POST',
    body: JSON.stringify({ paper_id: paperId, message }),
  })
}
