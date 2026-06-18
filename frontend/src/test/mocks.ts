import type { FeedCardSummary, CardDetail, FeedResponse } from '../types/feed'

export const mockCardSummary: FeedCardSummary = {
  card_id: '20260615_023000_abc123',
  paper_id: '2304.03442',
  hook: 'You built this cold two years ago. Stanford published it first.',
  why_you_now: 'This is the formal version of your cloning work.',
  time_estimate: '18 min',
  card_type: 'new_paper',
  created_at: '2026-06-15T02:30:00Z',
}

export const mockCardDetail: CardDetail = {
  card_id: '20260615_023000_abc123',
  paper_id: '2304.03442',
  source_url: 'https://arxiv.org/abs/2304.03442',
  hook: 'You built this cold two years ago. Stanford published it first.',
  why_you_now: 'This is the formal version of your cloning work.',
  time_estimate: '18 min',
  card_type: 'new_paper',
  created_at: '2026-06-15T02:30:00Z',
  digest: {
    gist: 'A one-paragraph summary of the paper.',
    key_ideas: ['Agents can reflect', 'Memory streams matter', 'Retrieval is key'],
    deep: 'A multi-paragraph deep dive into the paper methodology and results.',
  },
  glossary: [
    { term: 'Reflection', plain: 'When an agent pauses to synthesize observations.' },
    { term: 'Memory stream', plain: 'A time-ordered log of all agent experiences.' },
  ],
  math_notes: [
    { plain: 'Importance is scored by recency times relevance.', equation_optional: 'score = decay(t) * relevance(q, m)' },
  ],
  hypothesis_relevance: 'Supports the bet — architecture drives behavior, not raw model size.',
  honesty_note: 'Landmark paper. Worth a full read.',
  suggested_questions: ['What exactly is reflection?', 'Could I add this to my product?'],
}

export const mockFeedResponse: FeedResponse = {
  cards: [mockCardSummary],
  lastKey: null,
}

export const mockFeedResponseWithPagination: FeedResponse = {
  cards: [mockCardSummary],
  lastKey: { PK: 'USER#test#FEED', SK: 'CARD#20260614_000000' },
}
