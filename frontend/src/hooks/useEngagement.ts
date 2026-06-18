import { useRef, useEffect, useCallback } from 'react'
import { postEngagement } from '../api/engagement'
import type { EngagementEvent } from '../api/engagement'

interface UseEngagementOptions {
  paper_id: string
  card_id: string
}

export function useEngagement({ paper_id, card_id }: UseEngagementOptions) {
  const startTimeRef = useRef<number>(Date.now())
  const activeTimeRef = useRef<number>(0)
  const visibleRef = useRef<boolean>(true)
  const lastVisibleRef = useRef<number>(Date.now())
  const interactionsRef = useRef<number>(0)
  const scrollDepthRef = useRef<number>(0)
  const firedReadRef = useRef<boolean>(false)

  useEffect(() => {
    startTimeRef.current = Date.now()
    activeTimeRef.current = 0
    lastVisibleRef.current = Date.now()
    visibleRef.current = true
    interactionsRef.current = 0
    scrollDepthRef.current = 0
    firedReadRef.current = false

    const handleVisibilityChange = () => {
      if (document.hidden) {
        if (visibleRef.current) {
          activeTimeRef.current += Date.now() - lastVisibleRef.current
          visibleRef.current = false
        }
      } else {
        lastVisibleRef.current = Date.now()
        visibleRef.current = true
      }
    }

    document.addEventListener('visibilitychange', handleVisibilityChange)
    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange)
    }
  }, [paper_id, card_id])

  const getActiveMs = useCallback(() => {
    let ms = activeTimeRef.current
    if (visibleRef.current) {
      ms += Date.now() - lastVisibleRef.current
    }
    return ms
  }, [])

  const trackScroll = useCallback((depthPct: number) => {
    scrollDepthRef.current = Math.max(scrollDepthRef.current, Math.min(100, Math.round(depthPct)))
  }, [])

  const trackInteraction = useCallback(() => {
    interactionsRef.current += 1
  }, [])

  const fireEvent = useCallback((action: EngagementEvent['action'], extra?: Partial<EngagementEvent>) => {
    if (!paper_id) return
    const event: EngagementEvent = {
      paper_id,
      card_id,
      action,
      ...extra,
    }
    postEngagement(event).catch(() => {})
  }, [paper_id, card_id])

  const fireExpand = useCallback((section?: string) => {
    trackInteraction()
    fireEvent('expand', section ? { section } : undefined)
  }, [fireEvent, trackInteraction])

  const fireAsk = useCallback(() => {
    fireEvent('ask')
  }, [fireEvent])

  const fireRead = useCallback(() => {
    if (firedReadRef.current) return
    firedReadRef.current = true
    fireEvent('read', {
      active_ms: getActiveMs(),
      scroll_depth_pct: scrollDepthRef.current,
      interactions: interactionsRef.current,
    })
  }, [fireEvent, getActiveMs])

  const fireDismiss = useCallback(() => {
    fireEvent('dismiss', {
      active_ms: getActiveMs(),
      scroll_depth_pct: scrollDepthRef.current,
    })
  }, [fireEvent, getActiveMs])

  return {
    trackScroll,
    trackInteraction,
    fireEvent,
    fireExpand,
    fireAsk,
    fireRead,
    fireDismiss,
    getActiveMs,
    scrollDepthRef,
  }
}
