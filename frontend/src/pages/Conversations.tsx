import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { ArrowLeft, Plus, MessageCircle, FileText, Pencil, Check, Trash2 } from 'lucide-react'
import { apiFetch } from '../api/client'
import { LoadingSpinner } from '../components/LoadingSpinner'
import { Layout } from '../components/Layout'

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

function deleteConversation(convId: string): Promise<void> {
  return apiFetch('/conversations', {
    method: 'DELETE',
    body: JSON.stringify({ conv_id: convId }),
  })
}

interface ConversationItemProps {
  conv: Conversation
  index: number
  editing: boolean
  editTitle: string
  onNavigate: () => void
  onStartEdit: () => void
  onEditChange: (val: string) => void
  onSaveEdit: () => void
  onCancelEdit: () => void
  onDelete: () => void
  accent?: boolean
}

function ConversationItem({ conv, index, editing, editTitle, onNavigate, onStartEdit, onEditChange, onSaveEdit, onCancelEdit, onDelete, accent }: ConversationItemProps) {
  const [swipeX, setSwipeX] = useState(0)
  const [touchStartX, setTouchStartX] = useState(0)
  const [confirmDelete, setConfirmDelete] = useState(false)

  const handleTouchStart = (e: React.TouchEvent) => { setTouchStartX(e.touches[0].clientX) }
  const handleTouchMove = (e: React.TouchEvent) => {
    const diff = touchStartX - e.touches[0].clientX
    if (diff > 0) setSwipeX(Math.min(diff, 60))
  }
  const handleTouchEnd = () => {
    if (swipeX > 40) { onStartEdit() }
    setSwipeX(0)
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.03 }}
      className="relative overflow-hidden rounded-xl"
    >
      {/* Actions revealed by swipe */}
      <div className="absolute inset-y-0 right-0 flex items-center gap-2 px-3"
        style={{ width: '90px', opacity: swipeX > 10 ? 1 : 0 }}>
        <button onClick={onStartEdit} className="p-2 bg-accent/20 rounded-lg">
          <Pencil size={14} className="text-accent" />
        </button>
        <button onClick={() => setConfirmDelete(true)} className="p-2 bg-red-500/20 rounded-lg">
          <Trash2 size={14} className="text-red-400" />
        </button>
      </div>

      <div
        className={`relative feed-card ${accent ? 'feed-card--unread' : 'feed-card--read'} rounded-xl p-4 transition-transform group`}
        style={{ transform: `translateX(-${swipeX}px)` }}
        onTouchStart={handleTouchStart}
        onTouchMove={handleTouchMove}
        onTouchEnd={handleTouchEnd}
      >
        <div className="flex items-start gap-3">
          {accent ? (
            <MessageCircle size={12} className="text-accent mt-0.5 shrink-0" />
          ) : (
            <FileText size={12} className="text-zinc-500 mt-0.5 shrink-0" />
          )}
          <div className="flex-1 min-w-0 cursor-pointer" onClick={editing ? undefined : onNavigate}>
            {editing ? (
              <form onSubmit={(e) => { e.preventDefault(); onSaveEdit() }} className="flex items-center gap-2">
                <input
                  type="text"
                  value={editTitle}
                  onChange={(e) => onEditChange(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Escape') onCancelEdit() }}
                  autoFocus
                  className="flex-1 bg-white/[0.04] border border-white/[0.08] rounded-lg px-2 py-1 text-sm text-white focus:outline-none focus:border-accent/40"
                />
                <button type="submit" className="text-accent p-1"><Check size={14} /></button>
              </form>
            ) : (
              <p className={`text-sm font-medium truncate ${accent ? 'text-white/90' : 'text-zinc-400'}`}>
                {conv.title || 'New conversation'}
              </p>
            )}
            <p className={`text-[11px] mt-1 ${accent ? 'text-zinc-500' : 'text-zinc-600'}`}>
              {conv.turn_count} messages · {new Date(conv.last_active).toLocaleDateString()}
            </p>
          </div>
          {/* Desktop: hover to reveal edit + delete */}
          {!editing && !confirmDelete && (
            <div className="hidden group-hover:flex items-center gap-1 shrink-0">
              <button
                onClick={(e) => { e.stopPropagation(); onStartEdit() }}
                className="text-zinc-600 hover:text-accent p-1 transition-colors"
              >
                <Pencil size={14} />
              </button>
              <button
                onClick={(e) => { e.stopPropagation(); setConfirmDelete(true) }}
                className="text-zinc-600 hover:text-red-400 p-1 transition-colors"
              >
                <Trash2 size={14} />
              </button>
            </div>
          )}
          {confirmDelete && (
            <div className="flex items-center gap-1.5 shrink-0" onClick={(e) => e.stopPropagation()}>
              <span className="text-[11px] text-zinc-400">Delete?</span>
              <button onClick={() => { onDelete(); setConfirmDelete(false) }} className="text-[11px] text-red-400 font-medium">Yes</button>
              <button onClick={() => setConfirmDelete(false)} className="text-[11px] text-zinc-500 font-medium">No</button>
            </div>
          )}
        </div>
      </div>
    </motion.div>
  )
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
    <Layout>
    <div className="min-h-screen bg-[#0a0a0f] relative">
      <div className="ambient-orb w-72 h-72 bg-violet-neon top-[-5rem] left-[-5rem]" />
      <div className="max-w-lg lg:max-w-3xl mx-auto px-4 pt-safe-top pb-safe-bottom relative z-10">

        {/* Header */}
        <div className="glass-header sticky top-0 z-20 -mx-4 px-4 py-4 flex items-center justify-between">
          <button onClick={() => navigate('/')} className="text-sm text-zinc-400 hover:text-white transition-colors flex items-center gap-1 lg:hidden">
            <ArrowLeft size={18} /> Feed
          </button>
          <h1 className="text-sm font-semibold text-zinc-300 lg:text-xl lg:font-bold lg:text-gradient">Conversations</h1>
          <button
            onClick={() => createMutation.mutate()}
            disabled={createMutation.isPending}
            className="text-accent hover:text-white transition-colors p-2"
            title="New research conversation"
          >
            <Plus size={18} />
          </button>
        </div>

        {isLoading && <LoadingSpinner />}

        {/* Research conversations */}
        {researchConvs.length > 0 && (
          <div className="mt-4">
            <h2 className="text-xs text-zinc-500 uppercase tracking-wide font-medium mb-2 px-1">Research</h2>
            <div className="space-y-2">
              {researchConvs.map((conv, i) => (
                <ConversationItem
                  key={conv.conv_id}
                  conv={conv}
                  index={i}
                  editing={editingId === conv.conv_id}
                  editTitle={editTitle}
                  onNavigate={() => navigate(`/chat/research/${conv.conv_id}`)}
                  onStartEdit={() => { setEditingId(conv.conv_id); setEditTitle(conv.title || '') }}
                  onEditChange={setEditTitle}
                  onSaveEdit={() => {
                    updateTitle(conv.conv_id, editTitle).then(() => {
                      queryClient.invalidateQueries({ queryKey: ['conversations'] })
                      setEditingId(null)
                    })
                  }}
                  onCancelEdit={() => setEditingId(null)}
                  onDelete={() => { deleteConversation(conv.conv_id).then(() => queryClient.invalidateQueries({ queryKey: ['conversations'] })) }}
                  accent
                />
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
                <ConversationItem
                  key={conv.conv_id}
                  conv={conv}
                  index={i}
                  editing={editingId === conv.conv_id}
                  editTitle={editTitle}
                  onNavigate={() => navigate(`/chat/research/${conv.conv_id}`)}
                  onStartEdit={() => { setEditingId(conv.conv_id); setEditTitle(conv.title || '') }}
                  onEditChange={setEditTitle}
                  onSaveEdit={() => {
                    updateTitle(conv.conv_id, editTitle).then(() => {
                      queryClient.invalidateQueries({ queryKey: ['conversations'] })
                      setEditingId(null)
                    })
                  }}
                  onCancelEdit={() => setEditingId(null)}
                  onDelete={() => { deleteConversation(conv.conv_id).then(() => queryClient.invalidateQueries({ queryKey: ['conversations'] })) }}
                />
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
    </Layout>
  )
}
