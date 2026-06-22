import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { ArrowLeft, BookOpen, MessageCircle, ExternalLink, Bookmark, ThumbsUp } from 'lucide-react'
import { getLibrary } from '../api/library'
import { LoadingSpinner } from '../components/LoadingSpinner'
import type { LibraryEntry } from '../api/library'

function EngagementBar({ score }: { score: number }) {
  return (
    <div className="w-full h-1.5 bg-zinc-800 rounded-full overflow-hidden">
      <motion.div
        initial={{ width: 0 }}
        animate={{ width: `${score}%` }}
        transition={{ duration: 0.5, delay: 0.1 }}
        className={`h-full rounded-full ${
          score >= 70 ? 'bg-accent' : score >= 40 ? 'bg-violet-neon' : 'bg-zinc-600'
        }`}
      />
    </div>
  )
}

function ActionBadges({ actions, questionCount }: { actions: LibraryEntry['actions']; questionCount: number }) {
  return (
    <div className="flex items-center gap-2 flex-wrap">
      {actions.read && (
        <span className="text-xs text-zinc-400 flex items-center gap-1">
          <BookOpen size={10} /> Read
        </span>
      )}
      {actions.asked && (
        <span className="text-xs text-accent flex items-center gap-1">
          <MessageCircle size={10} /> {questionCount > 0 ? `${questionCount} questions` : 'Asked'}
        </span>
      )}
      {actions.source_clicked && (
        <span className="text-xs text-violet-neon flex items-center gap-1">
          <ExternalLink size={10} /> Source
        </span>
      )}
      {actions.bookmarked && (
        <span className="text-xs text-amber-400 flex items-center gap-1">
          <Bookmark size={10} fill="currentColor" /> Saved
        </span>
      )}
      {actions.rated_up && (
        <span className="text-xs text-green-400 flex items-center gap-1">
          <ThumbsUp size={10} fill="currentColor" />
        </span>
      )}
    </div>
  )
}

function LibraryCard({ entry, index }: { entry: LibraryEntry; index: number }) {
  const navigate = useNavigate()

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2, delay: index * 0.03 }}
      onClick={() => entry.card_id && navigate(`/card/${entry.card_id}`)}
      className="glass-card rounded-xl p-4 space-y-3 cursor-pointer active:scale-[0.99] transition-transform"
    >
      <EngagementBar score={entry.engagement_score} />

      <p className="text-sm font-medium text-white leading-snug">
        {entry.title}
      </p>

      <ActionBadges actions={entry.actions} questionCount={entry.question_count} />

      {entry.last_engaged && (
        <p className="text-xs text-zinc-600">
          Last engaged {new Date(entry.last_engaged).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
        </p>
      )}
    </motion.div>
  )
}

export function Library() {
  const navigate = useNavigate()
  const { data, isLoading, isError } = useQuery({
    queryKey: ['library'],
    queryFn: getLibrary,
  })

  return (
    <div className="min-h-screen bg-[#0a0a0f] relative">
      <div className="ambient-orb w-64 h-64 bg-accent top-[-5rem] right-[-5rem]" />
      <div className="max-w-lg mx-auto px-4 pt-safe-top pb-safe-bottom relative z-10">

        {/* Header */}
        <div className="glass-header sticky top-0 z-20 -mx-4 px-4 py-4 flex items-center justify-between">
          <button onClick={() => navigate('/')} className="text-sm text-zinc-400 hover:text-white transition-colors flex items-center gap-1">
            <ArrowLeft size={14} /> Feed
          </button>
          <h1 className="text-sm font-semibold text-zinc-300">Library</h1>
        </div>

        {/* Content */}
        {isLoading && <LoadingSpinner />}

        {isError && (
          <div className="text-center py-12">
            <p className="text-red-400 text-sm">Failed to load library</p>
          </div>
        )}

        {data && (
          <>
            <div className="py-4">
              <p className="text-xs text-zinc-500">
                {data.total} paper{data.total !== 1 ? 's' : ''} engaged with
              </p>
            </div>

            <div className="space-y-3 pb-8">
              {data.papers.map((entry, i) => (
                <LibraryCard key={entry.paper_id} entry={entry} index={i} />
              ))}
            </div>

            {data.total === 0 && (
              <div className="text-center py-20">
                <p className="text-zinc-500 text-sm">
                  No papers in your library yet. Read some from the feed!
                </p>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
