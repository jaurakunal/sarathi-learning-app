import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { LogOut, TrendingUp, BookOpen, Search, X, Target, Menu, MessageCircle, Inbox, Settings, Pause } from 'lucide-react'
import { getFeed } from '../api/feed'
import { postEngagement } from '../api/engagement'
import { apiFetch } from '../api/client'
import { FeedCard } from '../components/FeedCard'
import { LoadingSpinner } from '../components/LoadingSpinner'
import { PushBanner } from '../components/PushBanner'
import { Layout } from '../components/Layout'
import { logout } from '../auth/cognito'
import type { FeedResponse } from '../types/feed'

type TabFilter = 'all' | 'unread' | 'dismissed'

export function Feed() {
  const navigate = useNavigate()
  const [tab, setTab] = useState<TabFilter>('all')
  const [dismissed, setDismissed] = useState<Set<string>>(new Set())
  const [restored, setRestored] = useState<Set<string>>(new Set())
  const [searchQuery, setSearchQuery] = useState('')
  const [searchOpen, setSearchOpen] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)

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

  const { data: settingsData } = useQuery({
    queryKey: ['settings'],
    queryFn: () => apiFetch<{ pipeline_status: string }>('/settings'),
    staleTime: 60 * 1000,
  })
  const isPaused = settingsData?.pipeline_status === 'paused'

  const { data: dismissedData } = useInfiniteQuery<FeedResponse>({
    queryKey: ['feed-dismissed'],
    queryFn: ({ pageParam }) => getFeed(pageParam as Record<string, unknown> | null, 20, true),
    getNextPageParam: (lastPage) => lastPage.lastKey ?? undefined,
    initialPageParam: null,
    enabled: tab === 'dismissed',
  })

  const allCards = data?.pages.flatMap((page) => page.cards).filter((c) => !dismissed.has(c.card_id)) ?? []
  const dismissedCards = dismissedData?.pages.flatMap((page) => page.cards)
    .filter((c) => (c as any).dismissed && !restored.has(c.card_id)) ?? []

  const visibleCards = (() => {
    if (tab === 'dismissed') return dismissedCards
    const base = tab === 'unread' ? allCards.filter((c) => !c.read) : allCards
    if (!searchQuery) return base
    const q = searchQuery.toLowerCase()
    return base.filter((c) => c.hook?.toLowerCase().includes(q) || c.why_you_now?.toLowerCase().includes(q))
  })()

  const unreadCount = allCards.filter((c) => !c.read).length

  const handleDismiss = (cardId: string) => {
    setDismissed((prev) => new Set([...prev, cardId]))
  }

  const handleRestore = (cardId: string) => {
    setRestored((prev) => new Set([...prev, cardId]))
    postEngagement({ card_id: cardId, action: 'restore' }).catch(() => {})
  }

  return (
    <Layout>
    <div className="min-h-screen bg-[#0a0a0f] relative overflow-hidden">
      {/* Ambient glow orbs */}
      <div className="ambient-orb w-96 h-96 bg-accent top-[-10rem] right-[-10rem]" />
      <div className="ambient-orb w-72 h-72 bg-violet-neon bottom-[20%] left-[-8rem]" />

      <div className="max-w-lg lg:max-w-2xl xl:max-w-3xl mx-auto px-4 pt-safe-top pb-safe-bottom relative z-10">
        {/* Header */}
        <div className="glass-header sticky top-0 z-20 -mx-4 px-4 py-4 flex items-center justify-between">
          <h1 className="text-xl font-bold text-gradient lg:hidden">Sārathi</h1>
          <h1 className="text-xl font-bold text-gradient hidden lg:block">Feed</h1>
          <div className="flex items-center gap-1">
            <button
              onClick={() => { setSearchOpen(!searchOpen); if (searchOpen) setSearchQuery('') }}
              className={`p-2 transition-colors ${searchOpen ? 'text-accent' : 'text-zinc-500 hover:text-accent'}`}
              title="Search"
            >
              <Search size={18} />
            </button>
            <button
              onClick={() => setMenuOpen(true)}
              className="text-zinc-500 hover:text-accent transition-colors p-2 lg:hidden"
              title="Menu"
            >
              <Menu size={18} />
            </button>
          </div>
        </div>

        {/* Slide-out menu (mobile only) */}
        {menuOpen && (
          <>
            <div className="fixed inset-0 bg-black/60 z-40 lg:hidden" onClick={() => setMenuOpen(false)} />
            <div className="fixed top-0 right-0 h-full w-64 bg-[#0e0e18] border-l border-white/[0.06] z-50 p-6 pt-safe-top lg:hidden">
              <button onClick={() => setMenuOpen(false)} className="absolute top-4 right-4 text-zinc-500 hover:text-white p-2">
                <X size={18} />
              </button>
              <nav className="mt-12 space-y-1">
                <button onClick={() => { navigate('/conversations'); setMenuOpen(false) }} className="w-full flex items-center gap-3 px-3 py-3 rounded-lg text-sm text-zinc-300 hover:text-white hover:bg-white/[0.04] transition-colors">
                  <MessageCircle size={18} className="text-accent" /> Conversations
                </button>
                <button onClick={() => { navigate('/research'); setMenuOpen(false) }} className="w-full flex items-center gap-3 px-3 py-3 rounded-lg text-sm text-zinc-300 hover:text-white hover:bg-white/[0.04] transition-colors">
                  <Target size={18} className="text-zinc-400" /> Research
                </button>
                <button onClick={() => { navigate('/library'); setMenuOpen(false) }} className="w-full flex items-center gap-3 px-3 py-3 rounded-lg text-sm text-zinc-300 hover:text-white hover:bg-white/[0.04] transition-colors">
                  <BookOpen size={18} className="text-zinc-400" /> Library
                </button>
                <button onClick={() => { navigate('/profile'); setMenuOpen(false) }} className="w-full flex items-center gap-3 px-3 py-3 rounded-lg text-sm text-zinc-300 hover:text-white hover:bg-white/[0.04] transition-colors">
                  <TrendingUp size={18} className="text-zinc-400" /> Progress
                </button>
                <button onClick={() => { navigate('/settings'); setMenuOpen(false) }} className="w-full flex items-center gap-3 px-3 py-3 rounded-lg text-sm text-zinc-300 hover:text-white hover:bg-white/[0.04] transition-colors">
                  <Settings size={18} className="text-zinc-400" /> Settings
                </button>
                <div className="border-t border-white/[0.06] my-3" />
                <button onClick={() => { logout(); window.location.reload() }} className="w-full flex items-center gap-3 px-3 py-3 rounded-lg text-sm text-zinc-500 hover:text-red-400 hover:bg-red-400/5 transition-colors">
                  <LogOut size={18} /> Log out
                </button>
              </nav>
            </div>
          </>
        )}

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
                : 'text-zinc-500 hover:text-zinc-300 border border-transparent'
            }`}
          >
            All
          </button>
          <button
            onClick={() => setTab('unread')}
            className={`text-sm font-medium px-3 py-1.5 rounded-lg transition-all flex items-center gap-1.5 ${
              tab === 'unread'
                ? 'text-white bg-accent/20 border border-accent-dim'
                : 'text-zinc-500 hover:text-zinc-300 border border-transparent'
            }`}
          >
            Unread
            {unreadCount > 0 && (
              <span className="text-xs bg-violet-neon/20 text-violet-neon px-1.5 py-0.5 rounded-full font-semibold">
                {unreadCount}
              </span>
            )}
          </button>
          <button
            onClick={() => setTab('dismissed')}
            className={`text-sm font-medium px-3 py-1.5 rounded-lg transition-all ${
              tab === 'dismissed'
                ? 'text-white bg-accent/20 border border-accent-dim'
                : 'text-zinc-500 hover:text-zinc-300 border border-transparent'
            }`}
          >
            Dismissed
          </button>
        </div>

        {isPaused && (
          <div className="mx-0 mt-3 p-3 rounded-xl bg-amber-500/10 border border-amber-500/20 flex items-center gap-3">
            <Pause size={14} className="text-amber-400 shrink-0" />
            <p className="text-xs text-amber-300 flex-1">Paper discovery is paused.</p>
            <button
              onClick={() => navigate('/settings')}
              className="text-xs text-amber-400 hover:text-amber-300 font-medium shrink-0"
            >
              Resume
            </button>
          </div>
        )}

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

        {!isLoading && !isError && visibleCards.length === 0 && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="text-center py-20"
          >
            <Inbox size={32} className="text-zinc-700 mx-auto mb-3" />
            <p className="text-zinc-500 text-sm">
              {tab === 'dismissed'
                ? 'No dismissed cards.'
                : tab === 'unread'
                ? 'All caught up. Nice.'
                : 'No cards yet. The pipeline runs nightly at 2am UTC.'}
            </p>
          </motion.div>
        )}

        {/* Feed cards */}
        <div className="space-y-4 pb-8">
          {visibleCards.map((card, i) => (
            <FeedCard
              key={card.card_id}
              card={card}
              index={i}
              showRestore={tab === 'dismissed'}
              onDismiss={handleDismiss}
              onRestore={handleRestore}
            />
          ))}
        </div>

        {/* Load more */}
        {hasNextPage && (
          <div className="pb-8 text-center">
            <button
              onClick={() => fetchNextPage()}
              disabled={isFetchingNextPage}
              className="text-sm text-accent hover:text-accent-light transition-colors disabled:opacity-50 px-4 py-2 rounded-full border border-accent-dim hover:bg-accent/10"
            >
              {isFetchingNextPage ? 'Loading...' : 'Load more'}
            </button>
          </div>
        )}
      </div>
    </div>
    </Layout>
  )
}
