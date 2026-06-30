import { apiFetch } from './client'

export interface BriefSummary {
  week: string
  content: string
  generated_at: string
}

export interface BriefsResponse {
  briefs: BriefSummary[]
  next_after_week: string | null
}

export interface GetBriefsParams {
  limit?: number
  after_week?: string
}

export function getBriefs(params: GetBriefsParams = {}): Promise<BriefsResponse> {
  const qs = new URLSearchParams()
  if (params.limit !== undefined) qs.set('limit', String(params.limit))
  if (params.after_week) qs.set('after_week', params.after_week)
  const suffix = qs.toString() ? `?${qs.toString()}` : ''
  return apiFetch<BriefsResponse>(`/briefs${suffix}`)
}
