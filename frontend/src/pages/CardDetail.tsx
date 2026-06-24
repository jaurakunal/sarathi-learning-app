import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useEffect, useCallback, useRef, useState } from 'react'
import { ArrowLeft, Clock, MessageCircle, ExternalLink, Bookmark, ThumbsUp, ThumbsDown, Target, X, Plus } from 'lucide-react'
import { postEngagement } from '../api/engagement'
import { getCard } from '../api/feed'
import { CollapsibleSection } from '../components/CollapsibleSection'
import { Glossary } from '../components/Glossary'
import { MathNote } from '../components/MathNote'
import { LoadingSpinner } from '../components/LoadingSpinner'
import { useEngagement } from '../hooks/useEngagement'
import { Chat } from './Chat'

export function CardDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const contentRef = useRef<HTMLDivElement>(null)

  const { data: card, isLoading, isError } = useQuery({
    queryKey: ['card', id],
    queryFn: () => getCard(id!),
    enabled: !!id,
  })

  const [isBookmarked, setIsBookmarked] = useState(false)
  const [userRating, setUserRating] = useState<number | null>(null)
  const [isCore, setIsCore] = useState(false)
  const [tags, setTags] = useState<string[]>([])
  const [tagInput, setTagInput] = useState('')
  const [showTagging, setShowTagging] = useState(false)
  const [chatOpen, setChatOpen] = useState(false)
  const [isDesktop, setIsDesktop] = useState(() => typeof window !== 'undefined' && window.innerWidth >= 1024)

  useEffect(() => {
    const mq = window.matchMedia('(min-width: 1024px)')
    const handler = (e: MediaQueryListEvent) => setIsDesktop(e.matches)
    mq.addEventListener('change', handler)
    return () => mq.removeEventListener('change', handler)
  }, [])

  useEffect(() => {
    if (card) {
      setIsBookmarked(card.bookmarked ?? false)
      setUserRating(card.rating ?? null)
      setIsCore(card.relevance === 'core')
      setTags(card.tags ?? [])
    }
  }, [card?.card_id]) // eslint-disable-line react-hooks/exhaustive-deps

  const engagement = useEngagement({
    paper_id: card?.paper_id ?? '',
    card_id: card?.card_id ?? '',
  })
  const engagementRef = useRef(engagement)
  engagementRef.current = engagement

  // Keep stable refs for unmount cleanup (avoids stale closures)
  const paperIdRef = useRef('')
  const cardIdRef = useRef('')
  if (card?.paper_id) paperIdRef.current = card.paper_id
  if (card?.card_id) cardIdRef.current = card.card_id

  const navigatingToChatRef = useRef(false)

  // Track scroll depth
  const handleScroll = useCallback(() => {
    if (!contentRef.current) return
    const el = contentRef.current
    const scrolled = window.scrollY
    const total = el.scrollHeight - window.innerHeight
    if (total > 0) {
      engagement.trackScroll((scrolled / total) * 100)
    }
  }, [engagement])

  useEffect(() => {
    window.addEventListener('scroll', handleScroll, { passive: true })
    return () => window.removeEventListener('scroll', handleScroll)
  }, [handleScroll])

  // Fire "view" on mount (card was opened)
  useEffect(() => {
    if (card) engagement.fireView()
  }, [card?.card_id]) // eslint-disable-line react-hooks/exhaustive-deps

  // Fire "read" as soon as threshold is met (scroll >50% OR dwell >15s)
  // Fire "dismiss" on unmount only if read never triggered
  const firedReadRef = useRef(false)

  // Check dwell time every 5s
  useEffect(() => {
    if (!card) return
    const interval = setInterval(() => {
      if (firedReadRef.current) return
      const eng = engagementRef.current
      if (eng.getActiveMs() > 15000) {
        firedReadRef.current = true
        postEngagement({
          paper_id: paperIdRef.current,
          card_id: cardIdRef.current,
          action: 'read',
          active_ms: eng.getActiveMs(),
          scroll_depth_pct: eng.scrollDepthRef.current,
        }).catch(() => {})
        clearInterval(interval)
      }
    }, 5000)
    return () => clearInterval(interval)
  }, [card?.card_id]) // eslint-disable-line react-hooks/exhaustive-deps

  // Check scroll threshold on every scroll event
  const handleScrollForRead = useCallback(() => {
    if (firedReadRef.current) return
    const eng = engagementRef.current
    if (eng.scrollDepthRef.current > 50) {
      firedReadRef.current = true
      postEngagement({
        paper_id: paperIdRef.current,
        card_id: cardIdRef.current,
        action: 'read',
        active_ms: eng.getActiveMs(),
        scroll_depth_pct: eng.scrollDepthRef.current,
      }).catch(() => {})
    }
  }, [])

  useEffect(() => {
    window.addEventListener('scroll', handleScrollForRead, { passive: true })
    return () => window.removeEventListener('scroll', handleScrollForRead)
  }, [handleScrollForRead])

  // Fire "bounce" on unmount if read never fired (user opened but didn't engage deeply)
  useEffect(() => {
    return () => {
      if (navigatingToChatRef.current) return
      if (firedReadRef.current) return
      const pid = paperIdRef.current
      if (!pid) return
      const eng = engagementRef.current
      postEngagement({
        paper_id: pid,
        card_id: cardIdRef.current,
        action: 'view',
        active_ms: eng.getActiveMs(),
        scroll_depth_pct: eng.scrollDepthRef.current,
      }).catch(() => {})
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const handleAskQuestion = () => {
    engagement.fireAsk()
    if (isDesktop) {
      setChatOpen(true)
    } else {
      navigatingToChatRef.current = true
      navigate(`/card/${id}/chat`, { state: { paper_id: card?.paper_id } })
    }
  }

  if (isLoading) {
    return (
      <div className="min-h-screen bg-[#0a0a0f]">
        <LoadingSpinner />
      </div>
    )
  }

  if (isError || !card) {
    return (
      <div className="min-h-screen bg-[#0a0a0f] flex items-center justify-center">
        <div className="text-center space-y-3">
          <p className="text-red-400 text-sm">Card not found</p>
          <button
            onClick={() => navigate('/')}
            className="text-sm text-zinc-400 hover:text-white transition-colors"
          >
            ← Back to feed
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className={`min-h-screen bg-[#0a0a0f] relative ${chatOpen ? 'lg:flex' : ''}`} ref={contentRef}>
      <div className={`${chatOpen ? 'lg:w-1/2 lg:overflow-y-auto lg:h-screen' : ''} relative`}>
      <div className="ambient-orb w-72 h-72 bg-accent top-[-5rem] right-[-5rem]" />
      <div className={`${chatOpen ? 'max-w-none lg:px-8' : 'max-w-lg lg:max-w-3xl xl:max-w-4xl mx-auto'} px-4 pt-safe-top pb-safe-bottom relative z-10`}>
        {/* Header */}
        <div className="glass-header sticky top-0 z-20 -mx-4 px-4 py-4 flex items-center justify-between">
          <button
            onClick={() => navigate('/')}
            className="text-sm text-zinc-400 hover:text-white transition-colors flex items-center gap-1"
          >
            <ArrowLeft size={18} />
            Back
          </button>
          <button
            onClick={handleAskQuestion}
            className="text-xs font-medium text-accent border border-accent-dim px-3 py-1.5 rounded-lg hover:bg-accent/10 transition-all"
          >
            <span className="flex items-center gap-1.5">
              <MessageCircle size={14} />
              Ask a question
            </span>
          </button>
        </div>

        {/* Hook */}
        <div className="space-y-3 py-6 border-b border-white/[0.06] pb-6 mb-4">
          <div className="flex items-center gap-2">
            <Clock size={12} className="text-violet-neon" />
            <span className="text-xs text-violet-neon font-medium">{card.time_estimate}</span>
            {card.card_type !== 'new_paper' && (
              <span className="text-xs text-accent-light font-medium px-2 py-0.5 rounded-full bg-accent-dim">
                {card.card_type.replace('_', ' ')}
              </span>
            )}
          </div>
          <h1 className="text-xl font-bold text-white leading-snug">
            {card.hook}
          </h1>
          {card.why_you_now && (
            <p className="text-sm text-zinc-400 leading-relaxed">
              {card.why_you_now}
            </p>
          )}
        </div>

        {/* Sections — two columns on desktop */}
        <div className="lg:flex lg:gap-8">
          {/* Main reading content (left) */}
          <div className="lg:flex-1 space-y-0">
            {card.digest.gist && (
              <CollapsibleSection title="Gist" defaultOpen>
                <p className="text-sm text-zinc-300 leading-relaxed">
                  {card.digest.gist}
                </p>
              </CollapsibleSection>
            )}

            {card.digest.key_ideas?.length > 0 && (
              <CollapsibleSection title="Key Ideas" defaultOpen>
                <ul className="space-y-2">
                  {card.digest.key_ideas.map((idea, i) => (
                    <li key={i} className="text-sm text-zinc-300 leading-relaxed flex gap-2">
                      <span className="text-zinc-600 shrink-0">•</span>
                      <span>{idea}</span>
                    </li>
                  ))}
                </ul>
              </CollapsibleSection>
            )}

            {card.digest.deep && (
              <CollapsibleSection title="Deep Dive" onExpand={() => engagement.fireExpand('deep_dive')}>
                <p className="text-sm text-zinc-300 leading-relaxed whitespace-pre-line">
                  {card.digest.deep}
                </p>
              </CollapsibleSection>
            )}

            {card.hypothesis_relevance && (
              <CollapsibleSection title="For Your Hypothesis" defaultOpen>
                <p className="text-sm text-zinc-300 leading-relaxed italic">
                  {card.hypothesis_relevance}
                </p>
              </CollapsibleSection>
            )}
          </div>

          {/* Reference sidebar (right) — stacks below on mobile */}
          <div className="lg:w-80 lg:shrink-0 space-y-0 lg:border-l lg:border-white/[0.04] lg:pl-8">
            {card.glossary?.length > 0 && (
              <CollapsibleSection title="Glossary" onExpand={() => engagement.fireExpand('glossary')}>
                <Glossary items={card.glossary} />
              </CollapsibleSection>
            )}

            {card.math_notes?.length > 0 && (
              <CollapsibleSection title="Math Notes" onExpand={() => engagement.fireExpand('math_notes')}>
                <div className="space-y-3">
                  {card.math_notes.map((note, i) => (
                    <MathNote key={i} plain={note.plain} equation={note.equation_optional} />
                  ))}
                </div>
              </CollapsibleSection>
            )}

            {card.honesty_note && (
              <CollapsibleSection title="Honesty Note" defaultOpen>
                <p className="text-sm text-zinc-300 leading-relaxed">
                  {card.honesty_note}
                </p>
              </CollapsibleSection>
            )}

            {card.suggested_questions?.length > 0 && (
              <CollapsibleSection title="Questions You Might Ask" defaultOpen>
                <ul className="space-y-2">
                  {card.suggested_questions.map((q, i) => (
                    <li key={i} className="text-sm text-zinc-300 leading-relaxed flex gap-2">
                      <span className="text-zinc-600 shrink-0">?</span>
                      <span>{q}</span>
                    </li>
                  ))}
                </ul>
              </CollapsibleSection>
            )}
          </div>
        </div>

        {/* Actions bar */}
        <div className="pt-6 border-t border-white/5 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <button
              onClick={() => {
                const newState = !isBookmarked
                setIsBookmarked(newState)
                engagement.fireEvent('bookmark', { section: newState ? 'add' : 'remove' })
              }}
              className={`p-3 rounded-lg transition-colors ${
                isBookmarked
                  ? 'text-accent bg-accent/20'
                  : 'text-zinc-500 hover:text-accent hover:bg-accent/10'
              }`}
              title={isBookmarked ? 'Saved' : 'Save for later'}
            >
              <Bookmark size={14} fill={isBookmarked ? 'currentColor' : 'none'} />
            </button>
            <button
              onClick={() => {
                const newRating = userRating === 5 ? 0 : 5
                setUserRating(newRating || null)
                engagement.fireRate(newRating)
              }}
              className={`p-3 rounded-lg transition-colors ${
                userRating === 5
                  ? 'text-green-400 bg-green-400/20'
                  : 'text-zinc-500 hover:text-green-400 hover:bg-green-400/10'
              }`}
              title="Useful"
            >
              <ThumbsUp size={14} fill={userRating === 5 ? 'currentColor' : 'none'} />
            </button>
            <button
              onClick={() => {
                const newRating = userRating === 1 ? 0 : 1
                setUserRating(newRating || null)
                engagement.fireRate(newRating)
              }}
              className={`p-3 rounded-lg transition-colors ${
                userRating === 1
                  ? 'text-red-400 bg-red-400/20'
                  : 'text-zinc-500 hover:text-red-400 hover:bg-red-400/10'
              }`}
              title="Not useful"
            >
              <ThumbsDown size={14} fill={userRating === 1 ? 'currentColor' : 'none'} />
            </button>
          </div>
          {card.source_url && (
            <a
              href={card.source_url}
              target="_blank"
              rel="noopener noreferrer"
              onClick={() => engagement.fireSourceClick()}
              className="text-xs text-zinc-500 hover:text-accent transition-colors flex items-center gap-1"
            >
              Read full paper <ExternalLink size={12} />
            </a>
          )}
        </div>

        {/* Research tagging */}
        <div className="pt-4 mt-4 border-t border-white/5">
          <button
            onClick={() => {
              const newCore = !isCore
              setIsCore(newCore)
              if (!newCore) {
                setShowTagging(false)
              } else {
                setShowTagging(true)
              }
              postEngagement({
                card_id: card.card_id,
                action: 'tag',
                relevance: newCore ? 'core' : 'none',
                tags,
              }).catch(() => {})
            }}
            className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-all ${
              isCore
                ? 'text-accent bg-accent/15 border border-accent/30'
                : 'text-zinc-500 hover:text-accent hover:bg-accent/10 border border-transparent'
            }`}
          >
            <Target size={14} />
            {isCore ? 'Core to Research' : 'Mark as core to research'}
          </button>

          {(showTagging || tags.length > 0) && (
            <div className="mt-3 space-y-2">
              <div className="flex flex-wrap gap-1.5">
                {tags.map((tag) => (
                  <span key={tag} className="flex items-center gap-1 text-xs bg-accent/10 text-accent/80 px-2 py-1 rounded-md">
                    {tag}
                    <button
                      onClick={() => {
                        const newTags = tags.filter((t) => t !== tag)
                        setTags(newTags)
                        postEngagement({ card_id: card.card_id, action: 'tag', relevance: 'core', tags: newTags }).catch(() => {})
                      }}
                      className="text-accent/50 hover:text-accent"
                    >
                      <X size={12} />
                    </button>
                  </span>
                ))}
              </div>
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  value={tagInput}
                  onChange={(e) => setTagInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && tagInput.trim()) {
                      const newTags = [...tags, tagInput.trim()]
                      setTags(newTags)
                      setTagInput('')
                      postEngagement({ card_id: card.card_id, action: 'tag', relevance: 'core', tags: newTags }).catch(() => {})
                    }
                  }}
                  placeholder="Add tag (e.g., entity resolution)..."
                  className="flex-1 bg-white/[0.04] border border-white/[0.08] rounded-lg px-3 py-1.5 text-xs text-white placeholder-zinc-500 focus:outline-none focus:border-accent/40"
                />
                <button
                  onClick={() => {
                    if (tagInput.trim()) {
                      const newTags = [...tags, tagInput.trim()]
                      setTags(newTags)
                      setTagInput('')
                      postEngagement({ card_id: card.card_id, action: 'tag', relevance: 'core', tags: newTags }).catch(() => {})
                    }
                  }}
                  className="text-zinc-500 hover:text-accent p-1"
                >
                  <Plus size={14} />
                </button>
              </div>
            </div>
          )}
        </div>

        <div className="pb-12" />
      </div>
      </div>

      {/* Desktop chat panel */}
      {chatOpen && (
        <div className="hidden lg:block lg:w-1/2 lg:h-screen lg:border-l lg:border-white/[0.06] lg:relative">
          <Chat embedded paperId={card.paper_id} cardId={card.card_id} />
        </div>
      )}
    </div>
  )
}
