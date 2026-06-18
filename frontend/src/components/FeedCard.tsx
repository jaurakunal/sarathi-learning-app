import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { Clock, Check } from 'lucide-react'
import type { FeedCardSummary } from '../types/feed'

interface FeedCardProps {
  card: FeedCardSummary
  index: number
}

export function FeedCard({ card, index }: FeedCardProps) {
  const navigate = useNavigate()

  return (
    <motion.button
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, delay: index * 0.05 }}
      onClick={() => navigate(`/card/${card.card_id}`)}
      className={`w-full text-left glass-card rounded-2xl p-5 space-y-3 transition-all duration-200 active:scale-[0.98] ${
        card.read ? 'opacity-50' : ''
      }`}
    >
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Clock size={12} className="text-pink-hot" />
          <span className="text-xs text-pink-hot font-medium">
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
    </motion.button>
  )
}
