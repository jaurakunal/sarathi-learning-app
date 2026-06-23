import { useRef, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { Clock, Check, X, Undo2 } from 'lucide-react'
import { postEngagement } from '../api/engagement'
import type { FeedCardSummary } from '../types/feed'

interface FeedCardProps {
  card: FeedCardSummary
  index: number
  showRestore?: boolean
  onDismiss?: (cardId: string) => void
  onRestore?: (cardId: string) => void
}

export function FeedCard({ card, index, showRestore, onDismiss, onRestore }: FeedCardProps) {
  const navigate = useNavigate()
  const impressionFired = useRef(false)
  const cardRef = useRef<HTMLDivElement>(null)
  const [confirmDismiss, setConfirmDismiss] = useState(false)

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

  const handleDismissClick = (e: React.MouseEvent) => {
    e.stopPropagation()
    setConfirmDismiss(true)
  }

  const handleConfirmDismiss = (e: React.MouseEvent) => {
    e.stopPropagation()
    postEngagement({
      paper_id: card.paper_id,
      card_id: card.card_id,
      action: 'dismiss',
    }).catch(() => {})
    setConfirmDismiss(false)
    onDismiss?.(card.card_id)
  }

  const handleCancelDismiss = (e: React.MouseEvent) => {
    e.stopPropagation()
    setConfirmDismiss(false)
  }

  const handleRestore = (e: React.MouseEvent) => {
    e.stopPropagation()
    onRestore?.(card.card_id)
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
      {showRestore ? (
        <button
          onClick={handleRestore}
          className="absolute top-4 right-4 text-white/30 hover:text-accent transition-all p-1"
          title="Restore to feed"
        >
          <Undo2 size={14} />
        </button>
      ) : (
        <AnimatePresence>
          {confirmDismiss ? (
            <motion.div
              initial={{ opacity: 0, scale: 0.9 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0 }}
              className="absolute top-3 right-3 flex items-center gap-1.5 bg-black/80 border border-white/10 rounded-lg px-2 py-1.5"
              onClick={(e) => e.stopPropagation()}
            >
              <span className="text-[11px] text-zinc-400">Dismiss?</span>
              <button onClick={handleConfirmDismiss} className="text-[11px] text-red-400 hover:text-red-300 font-medium">Yes</button>
              <button onClick={handleCancelDismiss} className="text-[11px] text-zinc-500 hover:text-white font-medium">No</button>
            </motion.div>
          ) : (
            <button
              onClick={handleDismissClick}
              className="absolute top-4 right-4 text-white/20 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-all p-1"
              title="Not interested"
            >
              <X size={14} />
            </button>
          )}
        </AnimatePresence>
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
