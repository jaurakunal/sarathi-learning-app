import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { ChevronDown } from 'lucide-react'

interface CollapsibleSectionProps {
  title: string
  children: React.ReactNode
  defaultOpen?: boolean
  onExpand?: () => void
}

export function CollapsibleSection({ title, children, defaultOpen = false, onExpand }: CollapsibleSectionProps) {
  const [open, setOpen] = useState(defaultOpen)

  const handleClick = () => {
    const willOpen = !open
    setOpen(willOpen)
    if (willOpen && onExpand) {
      onExpand()
    }
  }

  return (
    <div className="border-t border-white/5">
      <button
        onClick={handleClick}
        className="w-full flex items-center justify-between py-3.5 text-left group"
      >
        <span className="text-xs font-semibold uppercase tracking-wider text-zinc-400 group-hover:text-zinc-300 transition-colors">
          {title}
        </span>
        <motion.span
          animate={{ rotate: open ? 180 : 0 }}
          transition={{ duration: 0.2 }}
          className="text-zinc-500"
        >
          <ChevronDown size={14} />
        </motion.span>
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2, ease: 'easeInOut' }}
            className="overflow-hidden"
          >
            <div className="pb-4">
              {children}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
