import type { ChatMessage as ChatMessageType } from '../types/chat'

interface ChatMessageProps {
  message: ChatMessageType
}

export function ChatMessage({ message }: ChatMessageProps) {
  const isUser = message.role === 'user'

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`max-w-[85%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
          isUser
            ? 'bg-zinc-700 text-white'
            : 'bg-zinc-900 border border-zinc-800 text-zinc-200'
        }`}
      >
        <p className="whitespace-pre-wrap">{message.content}</p>
        {message.streaming && (
          <span className="inline-block w-1.5 h-4 bg-zinc-400 animate-pulse ml-0.5 align-text-bottom" />
        )}
      </div>
    </div>
  )
}
