import { apiFetch } from './client'

export interface LibraryEntry {
  paper_id: string
  title: string
  card_id: string | null
  source_url: string
  engagement_score: number
  actions: {
    read: boolean
    asked: boolean
    bookmarked: boolean
    rated_up: boolean
    source_clicked: boolean
  }
  question_count: number
  total_active_ms: number
  first_engaged: string | null
  last_engaged: string | null
}

export interface LibraryResponse {
  papers: LibraryEntry[]
  total: number
}

export function getLibrary(): Promise<LibraryResponse> {
  return apiFetch<LibraryResponse>('/library')
}
