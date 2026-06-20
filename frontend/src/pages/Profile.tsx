import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { motion, AnimatePresence } from 'framer-motion'
import { ArrowLeft, BookOpen, MessageCircle, ExternalLink, Flame, Snowflake, ChevronDown } from 'lucide-react'
import { getProfile } from '../api/profile'
import { LoadingSpinner } from '../components/LoadingSpinner'
import type { TimelineEntry } from '../api/profile'

const STATUS_ICONS: Record<string, typeof Flame> = {
  hot: Flame,
  warm: Flame,
  active: Flame,
  cool: Snowflake,
  dormant: Snowflake,
}

const STATUS_COLORS: Record<string, string> = {
  hot: 'text-accent bg-accent/20',
  warm: 'text-amber-400 bg-amber-400/20',
  active: 'text-amber-400 bg-amber-400/20',
  cool: 'text-zinc-400 bg-zinc-700/50',
  dormant: 'text-zinc-500 bg-zinc-800/50',
}

function TimelineNode({ entry, isLast }: { entry: TimelineEntry; isLast: boolean }) {
  const [expanded, setExpanded] = useState(false)
  const date = new Date(entry.ts).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
  const snapshots = entry.frontier_snapshots || {}
  const hasDetail = Object.keys(snapshots).length > 0 || entry.hypothesis_evidence_added

  return (
    <div className="flex gap-4">
      {/* Timeline line + dot */}
      <div className="flex flex-col items-center">
        <div className="w-3 h-3 rounded-full bg-accent border-2 border-accent/50 shrink-0 mt-1" />
        {!isLast && <div className="w-px flex-1 bg-zinc-800 mt-1" />}
      </div>

      {/* Content */}
      <div className="pb-6 flex-1 min-w-0">
        <button
          onClick={() => hasDetail && setExpanded(!expanded)}
          className="w-full text-left group"
          disabled={!hasDetail}
        >
          <div className="flex items-center gap-2">
            <span className="text-xs text-zinc-500">{date}</span>
            {entry.changes.length > 0 && (
              <span className="text-xs text-accent/70">
                {entry.changes.filter(c => c.startsWith('area:')).map(c => c.replace('area:', '')).join(', ')}
              </span>
            )}
            {hasDetail && (
              <motion.span
                animate={{ rotate: expanded ? 180 : 0 }}
                className="text-zinc-600"
              >
                <ChevronDown size={12} />
              </motion.span>
            )}
          </div>
          {entry.changelog && entry.changelog !== 'Learn step ran with no changelog.' && (
            <p className="text-sm text-zinc-300 mt-1">{entry.changelog}</p>
          )}
        </button>

        <AnimatePresence>
          {expanded && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="overflow-hidden"
            >
              <div className="mt-3 space-y-3">
                {Object.entries(snapshots).map(([areaId, snap]) => (
                  <div key={areaId} className="glass-card rounded-lg p-3 space-y-2">
                    <span className="text-xs font-medium text-accent">{areaId}</span>
                    <div className="space-y-1">
                      <div className="flex gap-2">
                        <span className="text-xs text-zinc-600 shrink-0 mt-0.5">before:</span>
                        <p className="text-xs text-zinc-500 leading-relaxed">{snap.before.frontier || '(empty)'}</p>
                      </div>
                      <div className="flex gap-2">
                        <span className="text-xs text-green-500 shrink-0 mt-0.5">after:</span>
                        <p className="text-xs text-zinc-300 leading-relaxed">{snap.after.frontier}</p>
                      </div>
                    </div>
                  </div>
                ))}

                {entry.hypothesis_evidence_added && (
                  <div className="glass-card rounded-lg p-3">
                    <span className="text-xs font-medium text-violet-neon">Hypothesis evidence</span>
                    {entry.hypothesis_evidence_added.supporting?.map((s, i) => (
                      <p key={i} className="text-xs text-green-400 mt-1">+ {s}</p>
                    ))}
                    {entry.hypothesis_evidence_added.refuting?.map((s, i) => (
                      <p key={i} className="text-xs text-red-400 mt-1">− {s}</p>
                    ))}
                    {entry.hypothesis_evidence_added.refining?.map((s, i) => (
                      <p key={i} className="text-xs text-amber-400 mt-1">~ {s}</p>
                    ))}
                  </div>
                )}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  )
}

export function Profile() {
  const navigate = useNavigate()
  const { data, isLoading, isError } = useQuery({
    queryKey: ['profile'],
    queryFn: getProfile,
  })

  if (isLoading) return <div className="min-h-screen bg-[#0a0a0f]"><LoadingSpinner /></div>
  if (isError || !data) return <div className="min-h-screen bg-[#0a0a0f] flex items-center justify-center"><p className="text-red-400 text-sm">Failed to load profile</p></div>

  const { areas, hypothesis, stats_7d, timeline } = data

  return (
    <div className="min-h-screen bg-[#0a0a0f] relative">
      <div className="ambient-orb w-72 h-72 bg-violet-neon top-[-5rem] left-[-5rem]" />
      <div className="max-w-lg mx-auto px-4 pt-safe-top pb-safe-bottom relative z-10">

        {/* Header */}
        <div className="glass-header sticky top-0 z-20 -mx-4 px-4 py-4 flex items-center justify-between">
          <button onClick={() => navigate('/')} className="text-sm text-zinc-400 hover:text-white transition-colors flex items-center gap-1">
            <ArrowLeft size={14} /> Feed
          </button>
          <h1 className="text-sm font-semibold text-zinc-300">Progress</h1>
        </div>

        {/* Stats cards */}
        <div className="grid grid-cols-3 gap-2 py-4">
          <div className="glass-card rounded-xl p-3 text-center">
            <div className="text-lg font-bold text-white">{stats_7d.papers_read}</div>
            <div className="text-xs text-zinc-500 flex items-center justify-center gap-1"><BookOpen size={10} /> read</div>
          </div>
          <div className="glass-card rounded-xl p-3 text-center">
            <div className="text-lg font-bold text-white">{stats_7d.questions_asked}</div>
            <div className="text-xs text-zinc-500 flex items-center justify-center gap-1"><MessageCircle size={10} /> asked</div>
          </div>
          <div className="glass-card rounded-xl p-3 text-center">
            <div className="text-lg font-bold text-white">{stats_7d.source_clicks}</div>
            <div className="text-xs text-zinc-500 flex items-center justify-center gap-1"><ExternalLink size={10} /> deep</div>
          </div>
        </div>

        {/* Area status pills */}
        <div className="py-2">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-zinc-500 mb-2">Research Areas</h2>
          <div className="flex flex-wrap gap-2">
            {areas.map((area) => {
              const Icon = STATUS_ICONS[area.status] || Flame
              const colorClass = STATUS_COLORS[area.status] || STATUS_COLORS.active
              return (
                <div key={area.id} className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium ${colorClass}`}>
                  <Icon size={11} />
                  {area.name}
                </div>
              )
            })}
          </div>
        </div>

        {/* Hypothesis */}
        {hypothesis && (
          <div className="py-4">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-zinc-500 mb-2">Hypothesis</h2>
            <div className="glass-card rounded-xl p-4">
              <p className="text-sm text-zinc-200 italic">"{hypothesis.statement}"</p>
              <div className="mt-2 flex gap-3 text-xs">
                {hypothesis.supporting.length > 0 && (
                  <span className="text-green-400">+{hypothesis.supporting.length} supporting</span>
                )}
                {hypothesis.refuting.length > 0 && (
                  <span className="text-red-400">−{hypothesis.refuting.length} refuting</span>
                )}
                {hypothesis.refining.length > 0 && (
                  <span className="text-amber-400">~{hypothesis.refining.length} refining</span>
                )}
                {hypothesis.supporting.length === 0 && hypothesis.refuting.length === 0 && hypothesis.refining.length === 0 && (
                  <span className="text-zinc-500">No evidence yet</span>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Frontier Timeline */}
        <div className="py-4">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-zinc-500 mb-4">Frontier Evolution</h2>
          {(() => {
            const meaningfulEntries = timeline.filter(
              (e) => e.frontier_snapshots || e.hypothesis_evidence_added ||
                     (e.changelog && e.changelog !== 'Learn step ran with no changelog.')
            )
            return meaningfulEntries.length > 0 ? (
              <div>
                {meaningfulEntries.map((entry, i) => (
                  <TimelineNode key={entry.ts} entry={entry} isLast={i === meaningfulEntries.length - 1} />
                ))}
              </div>
            ) : (
              <p className="text-sm text-zinc-500">No learning updates yet. The pipeline runs nightly at 2am UTC.</p>
            )
          })()}
        </div>

        {/* Current frontiers */}
        <div className="py-4 pb-12">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-zinc-500 mb-3">Current Knowledge Edge</h2>
          <div className="space-y-3">
            {areas.map((area) => (
              <div key={area.id} className="glass-card rounded-xl p-4">
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-xs font-medium text-accent">{area.name}</span>
                  <span className={`text-xs px-1.5 py-0.5 rounded ${STATUS_COLORS[area.status] || ''}`}>{area.status}</span>
                </div>
                <p className="text-sm text-zinc-300 leading-relaxed">{area.frontier || 'Not yet established'}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
