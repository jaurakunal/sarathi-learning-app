import { getIdToken } from '../auth/cognito'
import type { ChatEvent } from '../types/chat'

const CHAT_URL = import.meta.env.VITE_CHAT_URL

export async function* streamChat(
  paperId: string,
  message: string,
): AsyncGenerator<ChatEvent> {
  const token = await getIdToken()
  if (!token) throw new Error('Not authenticated')

  const res = await fetch(CHAT_URL, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: token,
    },
    body: JSON.stringify({ paper_id: paperId, message }),
  })

  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.error || `Chat error: ${res.status}`)
  }

  const reader = res.body!.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })

    const lines = buffer.split('\n')
    buffer = lines.pop() || ''

    for (const line of lines) {
      if (line.startsWith('data: ')) {
        try {
          const event = JSON.parse(line.slice(6)) as ChatEvent
          yield event
        } catch {
          // Skip malformed lines
        }
      }
    }
  }

  // Process remaining buffer
  if (buffer.startsWith('data: ')) {
    try {
      yield JSON.parse(buffer.slice(6)) as ChatEvent
    } catch {
      // Skip
    }
  }
}
