import { useInfiniteQuery } from '@tanstack/react-query'
import { getFeed } from '../api/feed'
import { FeedCard } from '../components/FeedCard'
import { LoadingSpinner } from '../components/LoadingSpinner'
import { logout } from '../auth/cognito'
import type { FeedResponse } from '../types/feed'

export function Feed() {
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

  const cards = data?.pages.flatMap((page) => page.cards) ?? []

  return (
    <div className="min-h-screen bg-[#0a0a0f]">
      <div className="max-w-lg mx-auto px-4 pt-safe-top pb-safe-bottom">
        {/* Header */}
        <div className="flex items-center justify-between py-4 sticky top-0 bg-[#0a0a0f]/90 backdrop-blur-sm z-10">
          <h1 className="text-lg font-bold text-white">Sārathi</h1>
          <button
            onClick={() => { logout(); window.location.reload() }}
            className="text-xs text-zinc-500 hover:text-zinc-300 transition-colors"
          >
            Sign out
          </button>
        </div>

        {/* Content */}
        {isLoading && <LoadingSpinner />}

        {isError && (
          <div className="text-center py-12 space-y-3">
            <p className="text-red-400 text-sm">
              {error instanceof Error ? error.message : 'Failed to load feed'}
            </p>
            <button
              onClick={() => refetch()}
              className="text-sm text-zinc-400 hover:text-white transition-colors"
            >
              Try again
            </button>
          </div>
        )}

        {!isLoading && !isError && cards.length === 0 && (
          <div className="text-center py-20">
            <p className="text-zinc-500 text-sm">
              No cards yet. The pipeline runs nightly at 2am UTC.
            </p>
          </div>
        )}

        {/* Feed cards */}
        <div className="space-y-4 pb-8">
          {cards.map((card) => (
            <FeedCard key={card.card_id} card={card} />
          ))}
        </div>

        {/* Load more */}
        {hasNextPage && (
          <div className="pb-8 text-center">
            <button
              onClick={() => fetchNextPage()}
              disabled={isFetchingNextPage}
              className="text-sm text-zinc-400 hover:text-white transition-colors disabled:opacity-50"
            >
              {isFetchingNextPage ? 'Loading...' : 'Load more'}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
