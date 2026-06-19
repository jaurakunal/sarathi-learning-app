import { motion } from 'framer-motion'
import Markdown from 'react-markdown'
import type { ChatMessage as ChatMessageType } from '../types/chat'

interface ChatMessageProps {
  message: ChatMessageType
}

export function ChatMessage({ message }: ChatMessageProps) {
  const isUser = message.role === 'user'

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
      className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}
    >
      <div
        className={`max-w-[85%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
          isUser
            ? 'bg-accent/20 border border-accent-dim text-white'
            : 'glass-card text-zinc-200'
        }`}
      >
        {isUser ? (
          <p className="whitespace-pre-wrap">{message.content}</p>
        ) : (
          <div className="prose prose-invert prose-sm max-w-none prose-p:my-2 prose-ul:my-2 prose-ol:my-2 prose-li:my-0.5 prose-headings:my-3 prose-code:text-violet-neon prose-code:bg-surface prose-code:px-1 prose-code:rounded prose-pre:bg-surface prose-pre:border prose-pre:border-accent-dim prose-strong:text-white prose-a:text-accent">
            <Markdown>{message.content}</Markdown>
          </div>
        )}
        {message.streaming && (
          <span className="inline-block w-1.5 h-4 bg-accent animate-pulse ml-0.5 align-text-bottom rounded-sm" />
        )}
      </div>
    </motion.div>
  )
}
