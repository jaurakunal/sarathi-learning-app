import { useState, useRef, useEffect, useCallback } from 'react'
import { useParams, useNavigate, useLocation } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft } from 'lucide-react'
import { getChatHistory } from '../api/chat'
import { getCard } from '../api/feed'
import { postEngagement } from '../api/engagement'
import { client, SEND_MESSAGE, ON_CHUNK } from '../api/appsync'
import { ChatMessage } from '../components/ChatMessage'
import { ChatInput } from '../components/ChatInput'
import { ChatLoading } from '../components/ChatLoading'
import { SuggestionChips } from '../components/SuggestionChips'
import { LoadingSpinner } from '../components/LoadingSpinner'
import { apiFetch } from '../api/client'
import type { ChatMessage as ChatMessageType } from '../types/chat'

interface ChatProps {
  embedded?: boolean
  paperId?: string
  cardId?: string
  researchConvId?: string
}

export function Chat({ embedded, paperId: propPaperId, cardId: propCardId, researchConvId }: ChatProps = {}) {
  const { id: routeCardId } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const location = useLocation()
  const statePaperId = (location.state as { paper_id?: string })?.paper_id

  const cardId = propCardId || routeCardId
  const isResearch = !!researchConvId

  const { data: cardData } = useQuery({
    queryKey: ['card', cardId],
    queryFn: () => getCard(cardId!),
    enabled: !!cardId && !statePaperId && !propPaperId && !isResearch,
  })

  const paperId = isResearch ? researchConvId! : (propPaperId || statePaperId || cardData?.paper_id || '')

  const { data: history, isLoading: historyLoading } = useQuery({
    queryKey: ['chat-history', paperId],
    queryFn: () => getChatHistory(paperId),
    enabled: !!paperId,
  })

  const [messages, setMessages] = useState<ChatMessageType[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [suggestions, setSuggestions] = useState<string[]>([])
  const [suggestionsLoading, setSuggestionsLoading] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const historyLoadedRef = useRef(false)
  const turnCountRef = useRef(0)

  useEffect(() => {
    if (history && !historyLoadedRef.current) {
      historyLoadedRef.current = true
      const restored: ChatMessageType[] = []
      for (const turn of history.turns) {
        const seq = turn.seq as number
        if (turn.request) {
          restored.push({ role: 'user', content: turn.request, seq })
        }
        if (turn.response) {
          restored.push({ role: 'assistant', content: turn.response, seq, pinned: turn.pinned })
        }
      }
      if (restored.length > 0) {
        setMessages(restored)
      }
    }
  }, [history])

  // Load initial suggestions from card data, filtering out already-asked ones
  useEffect(() => {
    if (cardData?.suggested_questions && suggestions.length === 0) {
      const asked = new Set(messages.filter((m) => m.role === 'user').map((m) => m.content.toLowerCase()))
      const fresh = cardData.suggested_questions.filter(
        (q) => !asked.has(q.toLowerCase())
      )
      if (fresh.length > 0) {
        setSuggestions(fresh.slice(0, 3))
      }
    }
  }, [cardData, messages.length]) // eslint-disable-line react-hooks/exhaustive-deps

  const fetchSuggestions = useCallback(async () => {
    if (!paperId) return
    setSuggestionsLoading(true)
    try {
      const res = await apiFetch<{ suggestions: string[] }>('/suggestions', {
        method: 'POST',
        body: JSON.stringify({ paper_id: paperId }),
      })
      if (res.suggestions?.length) {
        const asked = new Set(messages.filter((m) => m.role === 'user').map((m) => m.content.toLowerCase()))
        const fresh = res.suggestions.filter((q) => !asked.has(q.toLowerCase()))
        setSuggestions(fresh.slice(0, 3))
      }
    } catch {
      // Non-critical
    } finally {
      setSuggestionsLoading(false)
    }
  }, [paperId, messages])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Cleanup subscription on unmount
  useEffect(() => {
    return () => { activeSubRef.current?.unsubscribe() }
  }, [])

  const activeSubRef = useRef<{ unsubscribe: () => void } | null>(null)

  const handleSend = useCallback(async (text: string) => {
    if (!paperId) return
    setError('')
    setLoading(true)

    // Unsubscribe from any previous subscription
    if (activeSubRef.current) {
      activeSubRef.current.unsubscribe()
      activeSubRef.current = null
    }

    // Calculate the seq for this new turn
    const newSeq = Math.floor(messages.filter((m) => m.role === 'user').length) + 1

    // Add user message + empty streaming assistant message
    setMessages((prev) => [
      ...prev,
      { role: 'user', content: text, seq: newSeq },
      { role: 'assistant', content: '', streaming: true, seq: newSeq },
    ])

    try {
      // Subscribe FIRST, then send — so we don't miss early chunks
      const sub = client.graphql({
        query: ON_CHUNK,
        variables: { conversationId: paperId },
      })

      // Set up subscription handler
      if ('subscribe' in sub) {
        activeSubRef.current = (sub as any).subscribe({
          next: ({ data }: any) => {
            const chunk = data?.onChunk
            if (!chunk) return

            if (chunk.done) {
              if (activeSubRef.current) {
                activeSubRef.current.unsubscribe()
                activeSubRef.current = null
              }
              // done chunk carries the full response — use it as authoritative content
              const fullResponse = chunk.chunk || ''
              if (fullResponse) {
                setMessages((prev) => {
                  const updated = [...prev]
                  const last = updated[updated.length - 1]
                  if (last?.role === 'assistant') {
                    updated[updated.length - 1] = { ...last, content: fullResponse, streaming: false, seq: chunk.turnSeq || last.seq }
                  }
                  return updated
                })
              } else {
                // Fallback: just clear streaming flag
                setMessages((prev) => {
                  const updated = [...prev]
                  const last = updated[updated.length - 1]
                  if (last?.role === 'assistant') {
                    updated[updated.length - 1] = { ...last, streaming: false }
                  }
                  return updated
                })
              }
              setLoading(false)
              // Fetch new suggestions after every response
              turnCountRef.current += 1
              fetchSuggestions()
            } else {
              setMessages((prev) => {
                const updated = [...prev]
                const last = updated[updated.length - 1]
                if (last?.role === 'assistant') {
                  updated[updated.length - 1] = {
                    ...last,
                    content: last.content + chunk.chunk,
                    streaming: true,
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

      // Small delay to ensure subscription is established before Lambda starts streaming
      await new Promise((r) => setTimeout(r, 500))

      // NOW send the mutation — Lambda will start streaming chunks
      const result = await client.graphql({
        query: SEND_MESSAGE,
        variables: { paperId, message: text },
      })

      const { status } = (result as any).data.sendMessage
      if (status.startsWith('error:')) {
        throw new Error(status.replace('error:', ''))
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
    <div className={`${embedded ? 'h-full' : 'min-h-screen'} bg-[#0a0a0f] flex flex-col relative`}>
      {!embedded && <div className="ambient-orb w-64 h-64 bg-violet-neon top-[-5rem] left-[-5rem]" />}

      {/* Header */}
      {embedded && (
        <div className="px-4 py-3 border-b border-white/[0.06] text-xs text-zinc-400 font-medium">Chat</div>
      )}
      {!embedded && (
        <div className="glass-header sticky top-0 z-20">
          <div className="max-w-lg lg:max-w-3xl mx-auto w-full px-4 py-4">
            <button
              onClick={() => navigate(isResearch ? '/conversations' : `/card/${cardId}`)}
              className="text-sm text-zinc-400 hover:text-white transition-colors flex items-center gap-1"
            >
              <ArrowLeft size={18} />
              {isResearch ? 'Conversations' : 'Back to paper'}
            </button>
          </div>
        </div>
      )}

      {/* Messages */}
      <div className={`flex-1 ${embedded ? 'px-4' : 'max-w-lg lg:max-w-3xl mx-auto w-full px-4'} py-4 space-y-4 overflow-y-auto relative z-10`}>
        {historyLoading && <LoadingSpinner />}

        {!historyLoading && messages.length === 0 && (
          <div className="text-center py-16">
            <p className="text-zinc-500 text-sm">
              {isResearch ? 'Ask anything across your research library.' : 'Ask anything about this paper.'}
            </p>
          </div>
        )}

        {messages.map((msg, i) => (
          msg.role === 'assistant' && msg.streaming && !msg.content ? null : (
          <ChatMessage
            key={i}
            message={msg}
            seq={msg.seq}
            onPin={paperId ? (seq) => {
              const isPinned = msg.pinned
              setMessages((prev) => prev.map((m, idx) => idx === i ? { ...m, pinned: !isPinned } : m))
              postEngagement({
                paper_id: paperId,
                action: isPinned ? 'unpin' : 'pin',
                seq,
              }).catch(() => {})
            } : undefined}
          />
          )
        ))}

        {loading && messages[messages.length - 1]?.content === '' && <ChatLoading />}

        {error && (
          <div className="text-center">
            <p className="text-red-400 text-xs">{error}</p>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Suggestions + Input */}
      <div className="relative z-10 border-t border-white/[0.08] bg-[#0a0a0f]/90 backdrop-blur-sm">
        <div className={`${embedded ? 'px-4' : 'max-w-lg lg:max-w-3xl mx-auto w-full px-4'} pt-3 ${embedded ? '' : 'pb-safe-bottom'}`}>
          {!loading && (
            <SuggestionChips
              suggestions={suggestions}
              onSelect={(q) => { setSuggestions([]); handleSend(q) }}
              loading={suggestionsLoading}
            />
          )}
          <div className="pt-2 pb-2">
            <ChatInput onSend={handleSend} disabled={loading || !paperId} />
          </div>
        </div>
      </div>
    </div>
  )
}

const logger = { error: console.error }
