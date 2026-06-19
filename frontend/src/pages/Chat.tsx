import { useState, useRef, useEffect, useCallback } from 'react'
import { useParams, useNavigate, useLocation } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft } from 'lucide-react'
import { getChatHistory } from '../api/chat'
import { getCard } from '../api/feed'
import { client, SEND_MESSAGE, ON_CHUNK } from '../api/appsync'
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

  const handleSend = useCallback(async (text: string) => {
    if (!paperId) return
    setError('')
    setLoading(true)

    // Add user message + empty streaming assistant message
    setMessages((prev) => [
      ...prev,
      { role: 'user', content: text },
      { role: 'assistant', content: '', streaming: true },
    ])

    try {
      // Send the mutation — this triggers the Lambda which streams back
      const result = await client.graphql({
        query: SEND_MESSAGE,
        variables: { paperId, message: text },
      })

      const { conversationId, turnSeq, status } = (result as any).data.sendMessage

      if (status.startsWith('error:')) {
        throw new Error(status.replace('error:', ''))
      }

      // Subscribe to chunks for this specific conversation + turn
      const sub = client.graphql({
        query: ON_CHUNK,
        variables: { conversationId, turnSeq },
      })

      // Handle the subscription
      if ('subscribe' in sub) {
        (sub as any).subscribe({
          next: ({ data }: any) => {
            const chunk = data?.onChunk
            if (!chunk) return

            if (chunk.done) {
              // Final chunk — mark streaming done
              setMessages((prev) => {
                const updated = [...prev]
                const last = updated[updated.length - 1]
                if (last?.role === 'assistant') {
                  updated[updated.length - 1] = { ...last, streaming: false }
                }
                return updated
              })
              setLoading(false)
            } else {
              // Append text chunk
              setMessages((prev) => {
                const updated = [...prev]
                const last = updated[updated.length - 1]
                if (last?.role === 'assistant') {
                  updated[updated.length - 1] = {
                    ...last,
                    content: last.content + chunk.chunk,
                  }
                }
                return updated
              })
            }
          },
          error: (err: any) => {
            logger.error('Subscription error:', err)
            setError('Stream connection lost')
            setLoading(false)
          },
        })
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to send message')
      // Remove empty assistant message on error
      setMessages((prev) => {
        const last = prev[prev.length - 1]
        if (last?.role === 'assistant' && !last.content) {
          return prev.slice(0, -1)
        }
        return prev
      })
      setLoading(false)
    }
  }, [paperId])

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

        {loading && messages[messages.length - 1]?.content === '' && <ChatLoading />}

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

const logger = { error: console.error }
