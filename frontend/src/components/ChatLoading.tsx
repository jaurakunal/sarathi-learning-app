import { motion } from 'framer-motion'

export function ChatLoading() {
  const text = 'Sārathi'
  const letters = text.split('')

  return (
    <div className="flex justify-start">
      <div className="glass-card rounded-2xl px-4 py-3 flex items-center gap-0.5">
        {letters.map((letter, i) => (
          <motion.span
            key={i}
            className="text-sm font-semibold text-gradient inline-block"
            style={{
              background: 'linear-gradient(135deg, #EC4899, #8B5CF6)',
              WebkitBackgroundClip: 'text',
              WebkitTextFillColor: 'transparent',
              backgroundClip: 'text',
            }}
            animate={{
              y: [0, -6, 0, 6, 0],
              opacity: [0.4, 1, 0.4, 1, 0.4],
            }}
            transition={{
              duration: 2.4,
              repeat: Infinity,
              delay: i * 0.15,
              ease: 'easeInOut',
            }}
          >
            {letter}
          </motion.span>
        ))}
        <motion.span
          className="ml-1 text-sm text-zinc-500"
          animate={{ opacity: [0, 1, 0] }}
          transition={{ duration: 1.5, repeat: Infinity }}
        >
          ∞
        </motion.span>
      </div>
    </div>
  )
}
