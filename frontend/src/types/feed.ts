export interface FeedCardSummary {
  card_id: string
  paper_id: string
  hook: string
  why_you_now: string
  time_estimate: string
  card_type: string
  created_at: string
  read: boolean
}

export interface CardDetail {
  card_id: string
  paper_id: string
  source_url: string
  hook: string
  why_you_now: string
  time_estimate: string
  card_type: string
  created_at: string
  digest: {
    gist: string
    key_ideas: string[]
    deep: string
  }
  glossary: { term: string; plain: string }[]
  math_notes: { plain: string; equation_optional?: string }[]
  hypothesis_relevance: string
  honesty_note: string
  suggested_questions: string[]
}

export interface FeedResponse {
  cards: FeedCardSummary[]
  lastKey: Record<string, unknown> | null
}
