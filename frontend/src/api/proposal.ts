import { apiFetch } from './client'

export type ProposalMode = 'bundle' | 'full'

export interface ProposalRequest {
  mode: ProposalMode
  area_id?: string | null
}

export interface ProposalResponse {
  markdown: string
  filename: string
  papers_included: number
  pinned_insights_included: number
  generated_at: string
  mode: ProposalMode
}

export function generateProposal(req: ProposalRequest): Promise<ProposalResponse> {
  return apiFetch<ProposalResponse>('/research/proposal', {
    method: 'POST',
    body: JSON.stringify({
      mode: req.mode,
      area_id: req.area_id || undefined,
    }),
  })
}
