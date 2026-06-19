import { useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { Clock, Check, X } from 'lucide-react'
import { postEngagement } from '../api/engagement'
import type { FeedCardSummary } from '../types/feed'

interface FeedCardProps {
  card: FeedCardSummary
  index: number
  onDismiss?: (cardId: string) => void
}

export function FeedCard({ card, index, onDismiss }: FeedCardProps) {
  const navigate = useNavigate()
  const impressionFired = useRef(false)
  const cardRef = useRef<HTMLDivElement>(null)

  // IntersectionObserver for impression tracking
  // Card must be 50% visible for 1.5s to count as a real impression (not fast scrolling)
  useEffect(() => {
    const el = cardRef.current
    if (!el || impressionFired.current) return

    let dwellTimer: ReturnType<typeof setTimeout> | null = null

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && !impressionFired.current) {
          dwellTimer = setTimeout(() => {
            if (!impressionFired.current) {
              impressionFired.current = true
              postEngagement({
                paper_id: card.paper_id,
                card_id: card.card_id,
                action: 'impression',
              }).catch(() => {})
              observer.disconnect()
            }
          }, 1500)
        } else if (dwellTimer) {
          clearTimeout(dwellTimer)
          dwellTimer = null
        }
      },
      { threshold: 0.5 },
    )
    observer.observe(el)
    return () => {
      observer.disconnect()
      if (dwellTimer) clearTimeout(dwellTimer)
    }
  }, [card.paper_id, card.card_id])

  const handleDismiss = (e: React.MouseEvent) => {
    e.stopPropagation()
    postEngagement({
      paper_id: card.paper_id,
      card_id: card.card_id,
      action: 'dismiss',
    }).catch(() => {})
    onDismiss?.(card.card_id)
  }

  return (
    <motion.div
      ref={cardRef}
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, delay: index * 0.05 }}
      onClick={() => navigate(`/card/${card.card_id}`)}
      role="button"
      className={`w-full text-left glass-card rounded-2xl p-5 space-y-3 transition-all duration-200 active:scale-[0.98] relative group cursor-pointer ${
        card.read ? 'opacity-50' : ''
      }`}
    >
      {/* Dismiss button */}
      {!card.read && (
        <button
          onClick={handleDismiss}
          className="absolute top-3 right-3 text-zinc-600 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-opacity p-1 rounded"
          title="Not interested"
        >
          <X size={14} />
        </button>
      )}

      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Clock size={12} className="text-violet-neon" />
          <span className="text-xs text-violet-neon font-medium">
            {card.time_estimate}
          </span>
          {card.read && (
            <span className="flex items-center gap-1 text-xs text-zinc-500">
              <Check size={10} />
              read
            </span>
          )}
        </div>
        {card.card_type !== 'new_paper' && (
          <span className="text-xs text-accent-light font-medium px-2 py-0.5 rounded-full bg-accent-dim">
            {card.card_type.replace('_', ' ')}
          </span>
        )}
      </div>

      <p className={`text-[17px] leading-snug font-semibold ${
        card.read ? 'text-zinc-400' : 'text-white'
      }`}>
        {card.hook}
      </p>

      {card.why_you_now && (
        <p className="text-sm text-zinc-400 leading-relaxed">
          {card.why_you_now}
        </p>
      )}
    </motion.div>
  )
}
