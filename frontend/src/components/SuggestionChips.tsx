import { motion, AnimatePresence } from 'framer-motion'

const MAX_DISPLAY_LEN = 50

function truncate(text: string): string {
  if (text.length <= MAX_DISPLAY_LEN) return text
  return text.slice(0, MAX_DISPLAY_LEN - 1) + '…'
}

interface SuggestionChipsProps {
  suggestions: string[]
  onSelect: (question: string) => void
  loading?: boolean
}

export function SuggestionChips({ suggestions, onSelect, loading }: SuggestionChipsProps) {
  if (!suggestions.length && !loading) return null

  return (
    <div className="relative">
    <div className="flex gap-2 overflow-x-auto pb-2 scrollbar-hide" style={{ maskImage: 'linear-gradient(to right, black 80%, transparent 100%)', WebkitMaskImage: 'linear-gradient(to right, black 80%, transparent 100%)' }}>
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
            title={q}
            className="shrink-0 text-xs text-accent/80 bg-accent/[0.06] border border-accent/20 hover:border-accent/40 hover:text-accent hover:bg-accent/10 px-3 py-2 rounded-full transition-all active:scale-95"
          >
            {truncate(q)}
          </motion.button>
        ))}
      </AnimatePresence>
    </div>
    </div>
  )
}
