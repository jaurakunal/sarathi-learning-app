import { useNavigate } from 'react-router-dom'
import type { FeedCardSummary } from '../types/feed'

interface FeedCardProps {
  card: FeedCardSummary
}

export function FeedCard({ card }: FeedCardProps) {
  const navigate = useNavigate()

  return (
    <button
      onClick={() => navigate(`/card/${card.card_id}`)}
      className={`w-full text-left border rounded-2xl p-5 space-y-3 active:scale-[0.98] transition-transform duration-100 ${
        card.read
          ? 'bg-zinc-900/20 border-zinc-800/50 opacity-60'
          : 'bg-zinc-900/50 border-zinc-800'
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className="text-xs text-zinc-500 font-medium">
            {card.time_estimate}
          </span>
          {card.read && (
            <span className="text-xs text-zinc-600">✓ read</span>
          )}
        </div>
        {card.card_type !== 'new_paper' && (
          <span className="text-xs text-amber-400/80 font-medium shrink-0">
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
    </button>
  )
}
