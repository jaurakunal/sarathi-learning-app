import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useEffect, useCallback, useRef } from 'react'
import { getCard } from '../api/feed'
import { CollapsibleSection } from '../components/CollapsibleSection'
import { Glossary } from '../components/Glossary'
import { MathNote } from '../components/MathNote'
import { LoadingSpinner } from '../components/LoadingSpinner'
import { useEngagement } from '../hooks/useEngagement'

export function CardDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const contentRef = useRef<HTMLDivElement>(null)

  const { data: card, isLoading, isError } = useQuery({
    queryKey: ['card', id],
    queryFn: () => getCard(id!),
    enabled: !!id,
  })

  const engagement = useEngagement({
    paper_id: card?.paper_id ?? '',
    card_id: card?.card_id ?? '',
  })
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

  // Fire "read" when leaving (back to feed), not when going deeper (chat)
  useEffect(() => {
    return () => {
      if (navigatingToChatRef.current) return
      if (engagement.scrollDepthRef.current > 50) {
        engagement.fireRead()
      }
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const handleAskQuestion = () => {
    navigatingToChatRef.current = true
    engagement.fireAsk()
    navigate(`/card/${id}/chat`, { state: { paper_id: card?.paper_id } })
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
    <div className="min-h-screen bg-[#0a0a0f]" ref={contentRef}>
      <div className="max-w-lg mx-auto px-4 pt-safe-top pb-safe-bottom">
        {/* Back button */}
        <div className="py-4 sticky top-0 bg-[#0a0a0f]/90 backdrop-blur-sm z-10 flex items-center justify-between">
          <button
            onClick={() => navigate('/')}
            className="text-sm text-zinc-400 hover:text-white transition-colors"
          >
            ← Back
          </button>
          <button
            onClick={handleAskQuestion}
            className="text-xs text-zinc-400 border border-zinc-700 px-3 py-1.5 rounded-lg hover:text-white hover:border-zinc-500 transition-colors"
          >
            Ask a question
          </button>
        </div>

        {/* Hook */}
        <div className="space-y-3 pb-6">
          <div className="flex items-center gap-2">
            <span className="text-xs text-zinc-500">{card.time_estimate}</span>
            {card.card_type !== 'new_paper' && (
              <span className="text-xs text-amber-400/80">
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

        {/* Sections */}
        <div className="space-y-0">
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

          {card.glossary?.length > 0 && (
            <CollapsibleSection title="Glossary" onExpand={() => engagement.fireExpand('glossary')}>
              <Glossary items={card.glossary} />
            </CollapsibleSection>
          )}

          {card.digest.deep && (
            <CollapsibleSection title="Deep Dive" onExpand={() => engagement.fireExpand('deep_dive')}>
              <p className="text-sm text-zinc-300 leading-relaxed whitespace-pre-line">
                {card.digest.deep}
              </p>
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

          {card.hypothesis_relevance && (
            <CollapsibleSection title="For Your Hypothesis" defaultOpen>
              <p className="text-sm text-zinc-300 leading-relaxed italic">
                {card.hypothesis_relevance}
              </p>
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

        {/* Source link */}
        {card.source_url && (
          <div className="pt-6 pb-12 border-t border-zinc-800">
            <a
              href={card.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-zinc-500 hover:text-zinc-300 transition-colors"
            >
              Read full paper ↗
            </a>
          </div>
        )}
      </div>
    </div>
  )
}
