import { motion, AnimatePresence } from 'framer-motion'

interface SuggestionChipsProps {
  suggestions: string[]
  onSelect: (question: string) => void
  loading?: boolean
}

export function SuggestionChips({ suggestions, onSelect, loading }: SuggestionChipsProps) {
  if (!suggestions.length && !loading) return null

  return (
    <div className="flex gap-2 overflow-x-auto pb-2 scrollbar-hide">
      <AnimatePresence mode="popLayout">
        {loading && !suggestions.length && (
          <motion.div
            key="loading"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="flex gap-2"
          >
            {[1, 2, 3].map((i) => (
              <div key={i} className="h-8 w-32 rounded-full bg-white/[0.04] animate-pulse shrink-0" />
            ))}
          </motion.div>
        )}
        {suggestions.map((q, i) => (
          <motion.button
            key={q}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.9 }}
            transition={{ delay: i * 0.05 }}
            onClick={() => onSelect(q)}
            className="shrink-0 text-xs text-zinc-300 bg-white/[0.04] border border-white/[0.08] hover:border-accent/30 hover:text-white px-3 py-2 rounded-full transition-all whitespace-nowrap"
          >
            {q}
          </motion.button>
        ))}
      </AnimatePresence>
    </div>
  )
}
