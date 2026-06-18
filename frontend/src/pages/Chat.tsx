import { useState, useRef, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { sendMessage } from '../api/chat'
import { ChatMessage } from '../components/ChatMessage'
import { ChatInput } from '../components/ChatInput'
import type { ChatMessage as ChatMessageType } from '../types/chat'

export function Chat() {
  const { id: paperId } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [messages, setMessages] = useState<ChatMessageType[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const messagesEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const handleSend = async (text: string) => {
    if (!paperId) return
    setError('')

    setMessages((prev) => [...prev, { role: 'user', content: text }])
    setMessages((prev) => [...prev, { role: 'assistant', content: '', streaming: true }])
    setLoading(true)

    try {
      const result = await sendMessage(paperId, text)
      setMessages((prev) => {
        const updated = [...prev]
        updated[updated.length - 1] = { role: 'assistant', content: result.response }
        return updated
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to get response')
      setMessages((prev) => {
        const last = prev[prev.length - 1]
        if (last?.role === 'assistant' && !last.content) {
          return prev.slice(0, -1)
        }
        return prev
      })
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-[#0a0a0f] flex flex-col">
      {/* Header */}
      <div className="max-w-lg mx-auto w-full px-4 py-4 sticky top-0 bg-[#0a0a0f]/90 backdrop-blur-sm z-10 border-b border-zinc-800/50">
        <button
          onClick={() => navigate(`/card/${paperId}`)}
          className="text-sm text-zinc-400 hover:text-white transition-colors"
        >
          ← Back to paper
        </button>
      </div>

      {/* Messages */}
      <div className="flex-1 max-w-lg mx-auto w-full px-4 py-4 space-y-4 overflow-y-auto">
        {messages.length === 0 && (
          <div className="text-center py-16">
            <p className="text-zinc-500 text-sm">
              Ask anything about this paper.
            </p>
          </div>
        )}

        {messages.map((msg, i) => (
          <ChatMessage key={i} message={msg} />
        ))}

        {error && (
          <div className="text-center">
            <p className="text-red-400 text-xs">{error}</p>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="max-w-lg mx-auto w-full px-4 py-4 pb-safe-bottom border-t border-zinc-800/50">
        <ChatInput onSend={handleSend} disabled={loading} />
      </div>
    </div>
  )
}
