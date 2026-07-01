import { useState, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { ChevronDown, Plus, Check, Pause } from 'lucide-react'
import {
  useActiveWorkspace,
  useWorkspaces,
  useSetActiveWorkspace,
} from '../hooks/useActiveWorkspace'

export function WorkspaceSwitcher() {
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement | null>(null)

  const active = useActiveWorkspace()
  const list = useWorkspaces()
  const setActive = useSetActiveWorkspace()

  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    if (open) {
      document.addEventListener('mousedown', onClick)
      return () => document.removeEventListener('mousedown', onClick)
    }
  }, [open])

  const activeName = active.data?.workspace?.name || 'No workspace'
  const workspaces = (list.data?.workspaces || []).filter(
    (w) => w.status !== 'archived',
  )

  return (
    <div ref={containerRef} className="relative inline-block">
      <button
        type="button"
        aria-label="Switch workspace"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 px-3 py-1.5 rounded-md text-sm bg-white/[0.04] border border-white/[0.08] text-zinc-200 hover:bg-white/[0.08]"
      >
        <span className="truncate max-w-[160px]">{activeName}</span>
        <ChevronDown size={14} className="text-zinc-400" />
      </button>

      {open && (
        <div
          role="menu"
          className="absolute left-0 mt-2 w-[210px] max-w-[calc(100vw-2rem)] bg-[#11111d] border border-white/[0.08] rounded-lg shadow-xl z-50 py-1"
        >
          {workspaces.length === 0 && (
            <div className="px-4 py-3 text-xs text-zinc-500">No workspaces yet</div>
          )}
          {workspaces.map((w) => {
            const isActive = w.workspace_id === active.data?.active_workspace_id
            return (
              <button
                key={w.workspace_id}
                role="menuitem"
                onClick={() => {
                  setActive.mutate(w.workspace_id, {
                    onSettled: () => setOpen(false),
                  })
                }}
                className={`w-full text-left px-4 py-2 flex items-center justify-between gap-3 hover:bg-white/[0.04] ${
                  isActive ? 'text-white' : 'text-zinc-300'
                }`}
              >
                <span className="flex items-center gap-2 min-w-0">
                  <span className="truncate text-sm">{w.name}</span>
                  {w.status === 'paused' && (
                    <Pause size={12} className="text-amber-400 shrink-0" />
                  )}
                </span>
                {isActive && <Check size={14} className="text-accent shrink-0" />}
              </button>
            )
          })}

          <div className="border-t border-white/[0.06] mt-1 pt-1">
            <button
              role="menuitem"
              onClick={() => {
                setOpen(false)
                navigate('/onboarding?new=true')
              }}
              className="w-full text-left px-4 py-2 flex items-center gap-2 text-sm text-accent hover:bg-white/[0.04]"
            >
              <Plus size={14} />
              Create new workspace
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
