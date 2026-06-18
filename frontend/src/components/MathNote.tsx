import { useState } from 'react'

interface MathNoteProps {
  plain: string
  equation?: string
}

export function MathNote({ plain, equation }: MathNoteProps) {
  const [showEquation, setShowEquation] = useState(false)

  return (
    <div className="space-y-1">
      <p className="text-sm text-zinc-300">{plain}</p>
      {equation && (
        <>
          {showEquation ? (
            <code className="block text-xs text-zinc-500 bg-zinc-800/50 px-3 py-2 rounded font-mono overflow-x-auto">
              {equation}
            </code>
          ) : (
            <button
              onClick={() => setShowEquation(true)}
              className="text-xs text-zinc-500 hover:text-zinc-300 transition-colors"
            >
              Show equation →
            </button>
          )}
        </>
      )}
    </div>
  )
}
