import { apiFetch } from './client'

export interface AreaInfo {
  id: string
  name: string
  status: string
  frontier: string
  last_engaged: string | null
}

export interface HypothesisInfo {
  statement: string
  supporting: string[]
  refuting: string[]
  refining: string[]
}

export interface FrontierSnapshot {
  before: { frontier: string; status: string }
  after: { frontier: string; status: string }
}

export interface TimelineEntry {
  ts: string
  type: string
  changelog: string
  changes: string[]
  frontier_snapshots?: Record<string, FrontierSnapshot>
  hypothesis_evidence_added?: { supporting?: string[]; refuting?: string[]; refining?: string[] }
}

export interface ProfileData {
  areas: AreaInfo[]
  hypothesis: HypothesisInfo | null
  summaries: Record<string, string>
  stats_7d: {
    papers_read: number
    papers_dismissed: number
    papers_bookmarked: number
    questions_asked: number
    source_clicks: number
    sections_expanded: number
    total_active_ms: number
  }
  timeline: TimelineEntry[]
  learning_style: Record<string, unknown> | null
  latest_brief: {
    week: string
    content: string
    created_at: string
    stats: { papers_read: number; questions_asked: number; source_clicks: number }
  } | null
  insights: { icon: string; text: string }[]
}

export function getProfile(): Promise<ProfileData> {
  return apiFetch<ProfileData>('/profile')
}
