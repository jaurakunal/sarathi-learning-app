export type ConnectionRelation = 'supports' | 'contradicts' | 'extends'

export interface ConnectionSide {
  paper_id: string
  card_id: string
  title: string
  claim: string
}

/** Present on `connect` cards: links today's paper to one already in the library. */
export interface Connection {
  relation: ConnectionRelation
  new: ConnectionSide
  related: ConnectionSide
}

export interface FeedCardSummary {
  card_id: string
  paper_id: string
  hook: string
  why_you_now: string
  time_estimate: string
  card_type: string
  created_at: string
  read: boolean
  bookmarked: boolean
  rating: number | null
  dismissed?: boolean
  /** Set on `connect` cards: how the new paper relates to a library paper. */
  relation?: ConnectionRelation | ''
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
  bookmarked?: boolean
  rating?: number | null
  relevance?: string
  tags?: string[]
  connection?: Connection
}

export interface FeedResponse {
  cards: FeedCardSummary[]
  lastKey: Record<string, unknown> | null
}
