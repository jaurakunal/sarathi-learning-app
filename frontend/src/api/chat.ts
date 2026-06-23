import { apiFetch } from './client'

export interface ChatResponse {
  conv_id: string
  turn_seq: number
  response: string
}

export interface ChatHistoryTurn {
  seq: number
  request: string
  response: string | null
  request_ts: string
  response_ts: string | null
  pinned?: boolean
}

export interface ChatHistory {
  turns: ChatHistoryTurn[]
  conv_id: string | null
}

export function sendMessage(paperId: string, message: string): Promise<ChatResponse> {
  return apiFetch<ChatResponse>('/chat', {
    method: 'POST',
    body: JSON.stringify({ paper_id: paperId, message }),
  })
}

export function getChatHistory(paperId: string): Promise<ChatHistory> {
  return apiFetch<ChatHistory>(`/chat/${encodeURIComponent(paperId)}`)
}
