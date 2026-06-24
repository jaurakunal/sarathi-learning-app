import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { ArrowLeft, Plus, MessageCircle, FileText, Pencil, Check } from 'lucide-react'
import { apiFetch } from '../api/client'
import { LoadingSpinner } from '../components/LoadingSpinner'

interface Conversation {
  conv_id: string
  scope: 'paper' | 'research'
  title: string
  paper_id: string
  last_active: string
  turn_count: number
}

function getConversations(): Promise<{ conversations: Conversation[] }> {
  return apiFetch('/conversations')
}

function createConversation(title: string): Promise<{ conv_id: string; title: string }> {
  return apiFetch('/conversations', {
    method: 'POST',
    body: JSON.stringify({ title }),
  })
}

function updateTitle(convId: string, title: string): Promise<void> {
  return apiFetch('/conversations', {
    method: 'PUT',
    body: JSON.stringify({ conv_id: convId, title }),
  })
}

export function Conversations() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [creating, setCreating] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editTitle, setEditTitle] = useState('')

  const { data, isLoading } = useQuery({
    queryKey: ['conversations'],
    queryFn: getConversations,
  })

  const createMutation = useMutation({
    mutationFn: () => createConversation(''),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ['conversations'] })
      navigate(`/chat/research/${result.conv_id}`)
    },
  })

  const conversations = data?.conversations ?? []
  const researchConvs = conversations.filter((c) => c.scope === 'research')
  const paperConvs = conversations.filter((c) => c.scope === 'paper')

  return (
    <div className="min-h-screen bg-[#0a0a0f] relative">
      <div className="ambient-orb w-72 h-72 bg-violet-neon top-[-5rem] left-[-5rem]" />
      <div className="max-w-lg mx-auto px-4 pt-safe-top pb-safe-bottom relative z-10">

        {/* Header */}
        <div className="glass-header sticky top-0 z-20 -mx-4 px-4 py-4 flex items-center justify-between">
          <button onClick={() => navigate('/')} className="text-sm text-zinc-400 hover:text-white transition-colors flex items-center gap-1">
            <ArrowLeft size={14} /> Feed
          </button>
          <h1 className="text-sm font-semibold text-zinc-300">Conversations</h1>
          <button
            onClick={() => createMutation.mutate()}
            disabled={createMutation.isPending}
            className="text-accent hover:text-white transition-colors p-2"
            title="New research conversation"
          >
            <Plus size={16} />
          </button>
        </div>

        {isLoading && <LoadingSpinner />}

        {/* Research conversations */}
        {researchConvs.length > 0 && (
          <div className="mt-4">
            <h2 className="text-xs text-zinc-500 uppercase tracking-wide font-medium mb-2 px-1">Research</h2>
            <div className="space-y-2">
              {researchConvs.map((conv, i) => (
                <motion.div
                  key={conv.conv_id}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: i * 0.03 }}
                  className="feed-card feed-card--unread rounded-xl p-4 transition-all hover:border-accent/30"
                >
                  <div className="flex items-start gap-3">
                    <MessageCircle size={14} className="text-accent mt-0.5 shrink-0" />
                    <div className="flex-1 min-w-0 cursor-pointer" onClick={() => navigate(`/chat/research/${conv.conv_id}`)}>
                      {editingId === conv.conv_id ? (
                        <form onSubmit={(e) => {
                          e.preventDefault()
                          updateTitle(conv.conv_id, editTitle).then(() => {
                            queryClient.invalidateQueries({ queryKey: ['conversations'] })
                            setEditingId(null)
                          })
                        }} className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
                          <input
                            type="text"
                            value={editTitle}
                            onChange={(e) => setEditTitle(e.target.value)}
                            autoFocus
                            className="flex-1 bg-white/[0.04] border border-white/[0.08] rounded-lg px-2 py-1 text-sm text-white focus:outline-none focus:border-accent/40"
                          />
                          <button type="submit" className="text-accent p-1"><Check size={14} /></button>
                        </form>
                      ) : (
                        <p className="text-sm text-white/90 font-medium truncate">
                          {conv.title || 'New conversation'}
                        </p>
                      )}
                      <p className="text-[11px] text-zinc-500 mt-1">
                        {conv.turn_count} messages · {new Date(conv.last_active).toLocaleDateString()}
                      </p>
                    </div>
                    {editingId !== conv.conv_id && (
                      <button
                        onClick={(e) => { e.stopPropagation(); setEditingId(conv.conv_id); setEditTitle(conv.title || '') }}
                        className="text-zinc-600 hover:text-zinc-300 p-1 shrink-0"
                      >
                        <Pencil size={12} />
                      </button>
                    )}
                  </div>
                </motion.div>
              ))}
            </div>
          </div>
        )}

        {/* Paper conversations */}
        {paperConvs.length > 0 && (
          <div className="mt-6">
            <h2 className="text-xs text-zinc-500 uppercase tracking-wide font-medium mb-2 px-1">Paper chats</h2>
            <div className="space-y-2">
              {paperConvs.map((conv, i) => (
                <motion.button
                  key={conv.conv_id}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: i * 0.03 }}
                  onClick={() => navigate(`/chat/research/${conv.conv_id}`)}
                  className="w-full text-left feed-card feed-card--read rounded-xl p-4 transition-all hover:opacity-80"
                >
                  <div className="flex items-start gap-3">
                    <FileText size={14} className="text-zinc-500 mt-0.5 shrink-0" />
                    <div className="flex-1 min-w-0">
                      <p className="text-sm text-zinc-400 font-medium truncate">
                        {conv.title || conv.paper_id.slice(0, 20)}
                      </p>
                      <p className="text-[11px] text-zinc-600 mt-1">
                        {conv.turn_count} messages · {new Date(conv.last_active).toLocaleDateString()}
                      </p>
                    </div>
                  </div>
                </motion.button>
              ))}
            </div>
          </div>
        )}

        {/* Empty state */}
        {!isLoading && conversations.length === 0 && (
          <div className="text-center py-20">
            <MessageCircle size={32} className="text-zinc-700 mx-auto mb-3" />
            <p className="text-zinc-500 text-sm">No conversations yet.</p>
            <button
              onClick={() => createMutation.mutate()}
              className="mt-3 text-sm text-accent hover:text-white transition-colors"
            >
              Start a research conversation
            </button>
          </div>
        )}

        <div className="pb-12" />
      </div>
    </div>
  )
}
