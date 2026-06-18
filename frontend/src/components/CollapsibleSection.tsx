import { useState } from 'react'

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
    <div className="border-t border-zinc-800">
      <button
        onClick={handleClick}
        className="w-full flex items-center justify-between py-3 text-left"
      >
        <span className="text-xs font-semibold uppercase tracking-wider text-zinc-400">
          {title}
        </span>
        <span className="text-zinc-500 text-sm">
          {open ? '−' : '+'}
        </span>
      </button>
      <div
        className={`overflow-hidden transition-all duration-150 ease-out ${
          open ? 'max-h-[2000px] opacity-100 pb-4' : 'max-h-0 opacity-0'
        }`}
      >
        {children}
      </div>
    </div>
  )
}
