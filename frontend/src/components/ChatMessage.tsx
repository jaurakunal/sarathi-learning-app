import { useState } from 'react'
import { motion } from 'framer-motion'
import Markdown from 'react-markdown'
import { Pin } from 'lucide-react'
import type { ChatMessage as ChatMessageType } from '../types/chat'

interface ChatMessageProps {
  message: ChatMessageType
  seq?: number
  onPin?: (seq: number) => void
}

export function ChatMessage({ message, seq, onPin }: ChatMessageProps) {
  const isUser = message.role === 'user'
  const [pinned, setPinned] = useState(message.pinned ?? false)

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
      className={`flex ${isUser ? 'justify-end' : 'justify-start'} group`}
    >
      <div
        className={`max-w-[85%] lg:max-w-[75%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
          isUser
            ? 'bg-accent/20 border border-accent-dim text-white'
            : `bg-[rgba(26,26,46,0.7)] backdrop-blur-[12px] border border-[rgba(236,72,153,0.15)] text-zinc-200 ${pinned ? 'border-accent/30' : ''}`
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
        {!isUser && !message.streaming && seq && onPin && (
          <div className="flex justify-end mt-2 pt-1.5 border-t border-white/[0.04]">
            <button
              onClick={(e) => {
                e.stopPropagation()
                e.preventDefault()
                setPinned(!pinned)
                onPin(seq)
              }}
              className={`flex items-center gap-1.5 px-2 py-1 rounded-md text-[11px] font-medium transition-all ${
                pinned
                  ? 'text-accent bg-accent/15'
                  : 'text-zinc-500 hover:text-accent hover:bg-accent/10'
              }`}
            >
              <Pin size={14} fill={pinned ? 'currentColor' : 'none'} />
              {pinned ? 'Pinned' : 'Pin insight'}
            </button>
          </div>
        )}
      </div>
    </motion.div>
  )
}
