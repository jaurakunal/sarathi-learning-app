export interface ChatStartEvent {
  type: 'start'
  conv_id: string
  turn_seq: number
}

export interface ChatChunkEvent {
  type: 'chunk'
  text: string
}

export interface ChatDoneEvent {
  type: 'done'
  tokens_in: number
  tokens_out: number
}

export interface ChatErrorEvent {
  type: 'error'
  message: string
}

export type ChatEvent = ChatStartEvent | ChatChunkEvent | ChatDoneEvent | ChatErrorEvent

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  streaming?: boolean
  seq?: number
  pinned?: boolean
}
