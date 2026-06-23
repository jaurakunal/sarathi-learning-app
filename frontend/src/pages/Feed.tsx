import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useInfiniteQuery } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { LogOut, TrendingUp, BookOpen, Search, X } from 'lucide-react'
import { getFeed } from '../api/feed'
import { FeedCard } from '../components/FeedCard'
import { LoadingSpinner } from '../components/LoadingSpinner'
import { PushBanner } from '../components/PushBanner'
import { logout } from '../auth/cognito'
import type { FeedResponse } from '../types/feed'

type TabFilter = 'all' | 'unread'

export function Feed() {
  const navigate = useNavigate()
  const [tab, setTab] = useState<TabFilter>('all')
  const [dismissed, setDismissed] = useState<Set<string>>(new Set())
  const [searchQuery, setSearchQuery] = useState('')
  const [searchOpen, setSearchOpen] = useState(false)

  const {
    data,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
    isLoading,
    isError,
    error,
    refetch,
  } = useInfiniteQuery<FeedResponse>({
    queryKey: ['feed'],
    queryFn: ({ pageParam }) => getFeed(pageParam as Record<string, unknown> | null),
    getNextPageParam: (lastPage) => lastPage.lastKey ?? undefined,
    initialPageParam: null,
  })

  const allCards = data?.pages.flatMap((page) => page.cards).filter((c) => !dismissed.has(c.card_id)) ?? []
  const filteredByTab = tab === 'unread' ? allCards.filter((c) => !c.read) : allCards
  const cards = searchQuery
    ? filteredByTab.filter((c) => {
        const q = searchQuery.toLowerCase()
        return c.hook?.toLowerCase().includes(q) || c.why_you_now?.toLowerCase().includes(q)
      })
    : filteredByTab
  const unreadCount = allCards.filter((c) => !c.read).length

  const handleDismiss = (cardId: string) => {
    setDismissed((prev) => new Set([...prev, cardId]))
  }

  return (
    <div className="min-h-screen bg-[#0a0a0f] relative overflow-hidden">
      {/* Ambient glow orbs */}
      <div className="ambient-orb w-96 h-96 bg-accent top-[-10rem] right-[-10rem]" />
      <div className="ambient-orb w-72 h-72 bg-violet-neon bottom-[20%] left-[-8rem]" />

      <div className="max-w-lg mx-auto px-4 pt-safe-top pb-safe-bottom relative z-10">
        {/* Header */}
        <div className="glass-header sticky top-0 z-20 -mx-4 px-4 py-4 flex items-center justify-between">
          <h1 className="text-xl font-bold text-gradient">Sārathi</h1>
          <div className="flex items-center gap-1">
            <button
              onClick={() => { setSearchOpen(!searchOpen); if (searchOpen) setSearchQuery('') }}
              className={`p-2 transition-colors ${searchOpen ? 'text-accent' : 'text-zinc-500 hover:text-accent'}`}
              title="Search"
            >
              <Search size={16} />
            </button>
            <button
              onClick={() => navigate('/library')}
              className="text-zinc-500 hover:text-accent transition-colors p-2"
              title="Library"
            >
              <BookOpen size={16} />
            </button>
            <button
              onClick={() => navigate('/profile')}
              className="text-zinc-500 hover:text-accent transition-colors p-2"
              title="Progress"
            >
              <TrendingUp size={16} />
            </button>
            <button
              onClick={() => { logout(); window.location.reload() }}
              className="text-zinc-500 hover:text-zinc-300 transition-colors p-2"
            >
              <LogOut size={16} />
            </button>
          </div>
        </div>

        {/* Search bar */}
        {searchOpen && (
          <div className="relative mt-3">
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search papers..."
              autoFocus
              className="w-full bg-white/[0.04] border border-white/[0.08] rounded-xl px-4 py-2.5 text-sm text-white placeholder-zinc-500 focus:outline-none focus:border-accent/40 transition-colors"
            />
            {searchQuery && (
              <button
                onClick={() => setSearchQuery('')}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-zinc-500 hover:text-white"
              >
                <X size={14} />
              </button>
            )}
          </div>
        )}

        {/* Tabs */}
        <div className="flex gap-1 py-4">
          <button
            onClick={() => setTab('all')}
            className={`text-sm font-medium px-3 py-1.5 rounded-lg transition-all ${
              tab === 'all'
                ? 'text-white bg-accent/20 border border-accent-dim'
                : 'text-zinc-500 hover:text-zinc-300'
            }`}
          >
            All
          </button>
          <button
            onClick={() => setTab('unread')}
            className={`text-sm font-medium px-3 py-1.5 rounded-lg transition-all flex items-center gap-1.5 ${
              tab === 'unread'
                ? 'text-white bg-accent/20 border border-accent-dim'
                : 'text-zinc-500 hover:text-zinc-300'
            }`}
          >
            Unread
            {unreadCount > 0 && (
              <span className="text-xs bg-violet-neon/20 text-violet-neon px-1.5 py-0.5 rounded-full font-semibold">
                {unreadCount}
              </span>
            )}
          </button>
        </div>

        <PushBanner />

        {/* Content */}
        {isLoading && <LoadingSpinner />}

        {isError && (
          <div className="text-center py-12 space-y-3">
            <p className="text-red-400 text-sm">
              {error instanceof Error ? error.message : 'Failed to load feed'}
            </p>
            <button
              onClick={() => refetch()}
              className="text-sm text-accent hover:text-accent-light transition-colors"
            >
              Try again
            </button>
          </div>
        )}

        {!isLoading && !isError && cards.length === 0 && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="text-center py-20"
          >
            <p className="text-zinc-500 text-sm">
              {tab === 'unread'
                ? 'All caught up. Nice.'
                : 'No cards yet. The pipeline runs nightly at 2am UTC.'}
            </p>
          </motion.div>
        )}

        {/* Feed cards */}
        <div className="space-y-4 pb-8">
          {cards.map((card, i) => (
            <FeedCard key={card.card_id} card={card} index={i} onDismiss={handleDismiss} />
          ))}
        </div>

        {/* Load more */}
        {hasNextPage && (
          <div className="pb-8 text-center">
            <button
              onClick={() => fetchNextPage()}
              disabled={isFetchingNextPage}
              className="text-sm text-accent hover:text-accent-light transition-colors disabled:opacity-50"
            >
              {isFetchingNextPage ? 'Loading...' : 'Load more'}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
