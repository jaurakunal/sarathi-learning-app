import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Target, Pin, FileText, Tag } from 'lucide-react'
import { apiFetch } from '../api/client'
import { LoadingSpinner } from '../components/LoadingSpinner'

interface PinnedInsight {
  seq: number
  request: string
  response: string
  pin_note: string
  pinned_at: string
}

interface CardSummary {
  card_id: string
  paper_id: string
  hook: string
  tags: string[]
  source_url: string
}

interface ResearchData {
  tag_groups: Record<string, CardSummary[]>
  untagged_engaged: CardSummary[]
  pinned_insights: Record<string, PinnedInsight[]>
  stats: {
    core_papers: number
    total_tags: number
    pinned_insights: number
    untagged_engaged: number
  }
}

function getResearch(): Promise<ResearchData> {
  return apiFetch('/research')
}

export function Research() {
  const navigate = useNavigate()
  const { data, isLoading } = useQuery({
    queryKey: ['research'],
    queryFn: getResearch,
  })

  if (isLoading) return <div className="min-h-screen bg-[#0a0a0f]"><LoadingSpinner /></div>
  if (!data) return null

  const { tag_groups, untagged_engaged, pinned_insights, stats } = data
  const tagNames = Object.keys(tag_groups).sort()

  return (
    <div className="min-h-screen bg-[#0a0a0f] relative">
      <div className="ambient-orb w-72 h-72 bg-accent top-[-5rem] right-[-5rem]" />
      <div className="max-w-lg mx-auto px-4 pt-safe-top pb-safe-bottom relative z-10">

        {/* Header */}
        <div className="glass-header sticky top-0 z-20 -mx-4 px-4 py-4">
          <div className="flex items-center justify-between">
            <button onClick={() => navigate('/')} className="text-sm text-zinc-400 hover:text-white transition-colors flex items-center gap-1">
              <ArrowLeft size={14} /> Feed
            </button>
            <h1 className="text-sm font-semibold text-zinc-300">Research</h1>
          </div>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-3 gap-3 mt-4">
          <div className="bg-white/[0.03] border border-white/[0.06] rounded-xl p-3 text-center">
            <p className="text-xl font-bold text-white">{stats.core_papers}</p>
            <p className="text-[10px] text-zinc-500 uppercase tracking-wide mt-1">Core Papers</p>
          </div>
          <div className="bg-white/[0.03] border border-white/[0.06] rounded-xl p-3 text-center">
            <p className="text-xl font-bold text-white">{stats.total_tags}</p>
            <p className="text-[10px] text-zinc-500 uppercase tracking-wide mt-1">Tags</p>
          </div>
          <div className="bg-white/[0.03] border border-white/[0.06] rounded-xl p-3 text-center">
            <p className="text-xl font-bold text-white">{stats.pinned_insights}</p>
            <p className="text-[10px] text-zinc-500 uppercase tracking-wide mt-1">Pinned Insights</p>
          </div>
        </div>

        {/* Tag groups */}
        {tagNames.length > 0 && (
          <div className="mt-8 space-y-6">
            {tagNames.map((tag) => (
              <div key={tag}>
                <div className="flex items-center gap-2 mb-3">
                  <Tag size={13} className="text-accent" />
                  <h2 className="text-sm font-semibold text-white">{tag}</h2>
                  <span className="text-[10px] text-zinc-500 bg-white/[0.04] px-1.5 py-0.5 rounded">
                    {tag_groups[tag].length}
                  </span>
                </div>
                <div className="space-y-2">
                  {tag_groups[tag].map((card) => (
                    <div
                      key={card.card_id}
                      onClick={() => navigate(`/card/${card.card_id}`)}
                      className="feed-card feed-card--unread rounded-xl p-4 cursor-pointer transition-all hover:border-accent/30"
                    >
                      <p className="text-sm text-white/90 font-medium leading-snug">{card.hook}</p>
                    </div>
                  ))}
                  {/* Pinned insights for papers in this tag */}
                  {tag_groups[tag].map((card) => {
                    const pins = pinned_insights[card.paper_id] || []
                    if (!pins.length) return null
                    return pins.map((pin) => (
                      <div key={`${card.paper_id}-${pin.seq}`} className="ml-4 pl-3 border-l-2 border-accent/20">
                        <div className="flex items-start gap-2">
                          <Pin size={11} className="text-accent mt-0.5 shrink-0" />
                          <div>
                            <p className="text-xs text-zinc-400 italic mb-1">"{pin.request}"</p>
                            <p className="text-xs text-zinc-300 leading-relaxed">{pin.response.slice(0, 200)}{pin.response.length > 200 ? '...' : ''}</p>
                          </div>
                        </div>
                      </div>
                    ))
                  })}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Untagged but engaged */}
        {untagged_engaged.length > 0 && (
          <div className="mt-8">
            <div className="flex items-center gap-2 mb-3">
              <FileText size={13} className="text-zinc-400" />
              <h2 className="text-sm font-semibold text-zinc-400">Engaged but untagged</h2>
              <span className="text-[10px] text-zinc-500 bg-white/[0.04] px-1.5 py-0.5 rounded">
                {untagged_engaged.length}
              </span>
            </div>
            <p className="text-xs text-zinc-500 mb-3">Papers you've bookmarked or rated highly — consider marking them as core and adding tags.</p>
            <div className="space-y-2">
              {untagged_engaged.map((card) => (
                <div
                  key={card.card_id}
                  onClick={() => navigate(`/card/${card.card_id}`)}
                  className="feed-card feed-card--read rounded-xl p-4 cursor-pointer transition-all hover:opacity-80"
                >
                  <p className="text-sm text-zinc-400 font-medium leading-snug">{card.hook}</p>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Empty state */}
        {stats.core_papers === 0 && stats.pinned_insights === 0 && (
          <div className="text-center py-20">
            <Target size={32} className="text-zinc-700 mx-auto mb-3" />
            <p className="text-zinc-500 text-sm">No research material yet.</p>
            <p className="text-zinc-600 text-xs mt-1">Mark papers as "Core to research" and pin chat insights to build your scaffold.</p>
          </div>
        )}

        <div className="pb-12" />
      </div>
    </div>
  )
}
