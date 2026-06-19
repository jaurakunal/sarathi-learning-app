import { useState, useRef, useEffect } from 'react'
import { useParams, useNavigate, useLocation } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft } from 'lucide-react'
import { sendMessage, getChatHistory } from '../api/chat'
import { getCard } from '../api/feed'
import { ChatMessage } from '../components/ChatMessage'
import { ChatInput } from '../components/ChatInput'
import { ChatLoading } from '../components/ChatLoading'
import { LoadingSpinner } from '../components/LoadingSpinner'
import type { ChatMessage as ChatMessageType } from '../types/chat'

export function Chat() {
  const { id: cardId } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const location = useLocation()
  const statePaperId = (location.state as { paper_id?: string })?.paper_id

  const { data: cardData } = useQuery({
    queryKey: ['card', cardId],
    queryFn: () => getCard(cardId!),
    enabled: !!cardId && !statePaperId,
  })

  const paperId = statePaperId || cardData?.paper_id || ''

  const { data: history, isLoading: historyLoading } = useQuery({
    queryKey: ['chat-history', paperId],
    queryFn: () => getChatHistory(paperId),
    enabled: !!paperId,
  })

  const [messages, setMessages] = useState<ChatMessageType[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const historyLoadedRef = useRef(false)

  useEffect(() => {
    if (history && !historyLoadedRef.current) {
      historyLoadedRef.current = true
      const restored: ChatMessageType[] = []
      for (const turn of history.turns) {
        if (turn.request) {
          restored.push({ role: 'user', content: turn.request })
        }
        if (turn.response) {
          restored.push({ role: 'assistant', content: turn.response })
        }
      }
      if (restored.length > 0) {
        setMessages(restored)
      }
    }
  }, [history])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const handleSend = async (text: string) => {
    if (!paperId) return
    setError('')

    setMessages((prev) => [...prev, { role: 'user', content: text }])
    setLoading(true)

    try {
      const result = await sendMessage(paperId, text)
      setMessages((prev) => [...prev, { role: 'assistant', content: result.response }])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to get response')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-[#0a0a0f] flex flex-col relative">
      <div className="ambient-orb w-64 h-64 bg-violet-neon top-[-5rem] left-[-5rem]" />

      {/* Header */}
      <div className="glass-header sticky top-0 z-20">
        <div className="max-w-lg mx-auto w-full px-4 py-4">
          <button
            onClick={() => navigate(`/card/${cardId}`)}
            className="text-sm text-zinc-400 hover:text-white transition-colors flex items-center gap-1"
          >
            <ArrowLeft size={14} />
            Back to paper
          </button>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 max-w-lg mx-auto w-full px-4 py-4 space-y-4 overflow-y-auto relative z-10">
        {historyLoading && <LoadingSpinner />}

        {!historyLoading && messages.length === 0 && (
          <div className="text-center py-16">
            <p className="text-zinc-500 text-sm">
              Ask anything about this paper.
            </p>
          </div>
        )}

        {messages.map((msg, i) => (
          <ChatMessage key={i} message={msg} />
        ))}

        {loading && <ChatLoading />}

        {error && (
          <div className="text-center">
            <p className="text-red-400 text-xs">{error}</p>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="relative z-10 border-t border-white/5">
        <div className="max-w-lg mx-auto w-full px-4 py-4 pb-safe-bottom">
          <ChatInput onSend={handleSend} disabled={loading || !paperId} />
        </div>
      </div>
    </div>
  )
}
