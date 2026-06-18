import Markdown from 'react-markdown'
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
        {isUser ? (
          <p className="whitespace-pre-wrap">{message.content}</p>
        ) : (
          <div className="prose prose-invert prose-sm max-w-none prose-p:my-2 prose-ul:my-2 prose-ol:my-2 prose-li:my-0.5 prose-headings:my-3 prose-code:text-zinc-300 prose-code:bg-zinc-800 prose-code:px-1 prose-code:rounded prose-pre:bg-zinc-800 prose-pre:border prose-pre:border-zinc-700">
            <Markdown>{message.content}</Markdown>
          </div>
        )}
        {message.streaming && (
          <span className="inline-block w-1.5 h-4 bg-zinc-400 animate-pulse ml-0.5 align-text-bottom" />
        )}
      </div>
    </div>
  )
}
