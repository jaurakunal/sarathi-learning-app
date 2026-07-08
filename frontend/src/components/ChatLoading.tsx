import { motion } from 'framer-motion'

export function ChatLoading() {
  return (
    <div className="flex justify-start" role="status" aria-label="Sārathi is thinking">
      <div className="glass-card rounded-2xl px-4 py-3 flex items-center gap-1.5">
        {[0, 1, 2].map((i) => (
          <motion.span
            key={i}
            className="w-1.5 h-1.5 rounded-full bg-accent"
            animate={{ y: [0, -4, 0] }}
            transition={{
              duration: 1,
              repeat: Infinity,
              delay: i * 0.15,
              ease: 'easeInOut',
            }}
          />
        ))}
      </div>
    </div>
  )
}
