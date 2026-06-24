import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { ArrowLeft, Plus, MessageCircle, FileText } from 'lucide-react'
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

export function Conversations() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [creating, setCreating] = useState(false)

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
                <motion.button
                  key={conv.conv_id}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: i * 0.03 }}
                  onClick={() => navigate(`/chat/research/${conv.conv_id}`)}
                  className="w-full text-left feed-card feed-card--unread rounded-xl p-4 transition-all hover:border-accent/30"
                >
                  <div className="flex items-start gap-3">
                    <MessageCircle size={14} className="text-accent mt-0.5 shrink-0" />
                    <div className="flex-1 min-w-0">
                      <p className="text-sm text-white/90 font-medium truncate">
                        {conv.title || 'New conversation'}
                      </p>
                      <p className="text-[11px] text-zinc-500 mt-1">
                        {conv.turn_count} messages · {new Date(conv.last_active).toLocaleDateString()}
                      </p>
                    </div>
                  </div>
                </motion.button>
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
                  onClick={() => navigate(`/card/${conv.conv_id}/chat`, { state: { paper_id: conv.paper_id } })}
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
