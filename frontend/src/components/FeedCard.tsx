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
      className={`feed-card w-full text-left rounded-2xl p-6 relative group cursor-pointer transition-all duration-300 active:scale-[0.98] ${
        card.read ? 'feed-card--read' : 'feed-card--unread'
      }`}
    >
      {!card.read && (
        <button
          onClick={handleDismiss}
          className="absolute top-4 right-4 text-white/20 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-all p-1"
          title="Not interested"
        >
          <X size={14} />
        </button>
      )}

      <p className={`text-[19px] leading-[1.35] font-semibold tracking-tight ${
        card.read ? 'text-zinc-500' : 'text-white/95'
      }`}>
        {card.hook}
      </p>

      {card.why_you_now && !card.read && (
        <p className="text-[13px] text-white/40 leading-relaxed mt-3 line-clamp-2">
          {card.why_you_now}
        </p>
      )}

      <div className="flex items-center gap-3 mt-4 pt-3 border-t border-white/[0.04]">
        <span className="flex items-center gap-1.5 text-[11px] text-white/35 font-medium tracking-wide uppercase">
          <Clock size={10} />
          {card.time_estimate}
        </span>
        {card.read && (
          <span className="flex items-center gap-1 text-[11px] text-white/25">
            <Check size={10} />
            read
          </span>
        )}
      </div>
    </motion.div>
  )
}
