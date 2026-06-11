# 08 — M0 Frontend Plan

**Goal:** A scrollable feed on your phone that makes you want to tap instead of opening Twitter. That's it. Everything else is M1+.

---

## What you're looking at (the experience)

```
┌────────────────────────────────────┐
│  Sārathi                    [≡]    │  ← minimal header, no nav for v0
├────────────────────────────────────┤
│                                    │
│  ┌──────────────────────────────┐  │
│  │ 🔬 18 min read               │  │  ← time estimate badge
│  │                              │  │
│  │ You built this cold two      │  │  ← THE HOOK (2 lines max,
│  │ years ago. Stanford          │  │     bold, large font)
│  │ published it first — and     │  │
│  │ they added the one piece     │  │
│  │ you were missing.            │  │
│  │                              │  │
│  │ Why now: This is the formal  │  │  ← why_you_now (smaller, muted)
│  │ version of your cloning...   │  │
│  │                              │  │
│  │ [Expand ▾]                   │  │  ← tap to show digest levels
│  └──────────────────────────────┘  │
│                                    │
│  ┌──────────────────────────────┐  │  ← next card
│  │ 🔬 12 min read               │  │
│  │                              │  │
│  │ Everyone assumed memory      │  │
│  │ decay was a bug. This paper  │  │
│  │ says it's the feature...     │  │
│  │                              │  │
│  └──────────────────────────────┘  │
│                                    │
│          (scroll for more)         │
└────────────────────────────────────┘
```

**When you tap "Expand" on a card:**

```
┌──────────────────────────────────┐
│ ← Back                           │
│                                  │
│ [HOOK — same as above, bold]     │
│                                  │
│ ─── Gist ────────────────────    │
│ One paragraph plain-language...  │
│                                  │
│ ─── Key Ideas ───────────────    │
│ • Idea 1                         │
│ • Idea 2                         │
│ • Idea 3                         │
│                                  │
│ ─── Glossary ────────────────    │
│ Reflection: When an agent...     │
│ Memory stream: The raw log...    │
│                                  │
│ ─── Deep Dive ───────────────    │  ← collapsed by default
│ [Tap to expand]                  │
│                                  │
│ ─── For Your Hypothesis ─────    │
│ "Supports the bet — the          │
│ architecture drives behavior,    │
│ not raw model size."             │
│                                  │
│ ─── Honesty Note ────────────    │
│ Landmark paper. Worth a full     │
│ read — not hype.                 │
│                                  │
│ ─── Questions You Might Ask ──   │
│ • What exactly is reflection?    │
│ • Could I add this to my product?│
│                                  │
│ [Read Full Paper ↗]              │  ← links to source_url
└──────────────────────────────────┘
```

---

## Tech decisions for M0

| Decision | Choice | Why |
|---|---|---|
| Framework | **React + Vite** | Fast to scaffold, you know JS, great mobile perf, huge ecosystem |
| Styling | **Tailwind CSS** | Utility-first, responsive-by-default, no CSS files to manage |
| State mgmt | **React Query (TanStack Query)** | Handles API caching, pagination, loading states — no Redux overhead |
| Auth | **AWS Amplify Auth** (just the auth module, not the full framework) | Wraps Cognito, handles tokens, 5 lines of config |
| Deployment | **S3 + CloudFront** (already in CDK stack) | Static SPA, already deployed |
| Mobile | **Responsive web** (not a native app) | Opens in phone browser, no app store overhead |

---

## Pages (v0 = only 2)

| Page | Route | What it does |
|---|---|---|
| **Feed** | `/` | Scrollable list of cards. Paginated (infinite scroll or "load more" button). Each card shows: hook, why_you_now, time_estimate. Tap expands to detail view. |
| **Card Detail** | `/card/:id` | Full card: hook, gist, key_ideas, glossary, math_notes (with tap-to-reveal equations), hypothesis_relevance, honesty_note, suggested_questions, link to source paper. |

No settings page, no profile page, no library page, no conversation page — those are M1.

---

## Components

```
src/
  App.tsx                 ← router setup + auth gate
  main.tsx                ← Vite entry
  api/
    client.ts             ← axios/fetch wrapper with Cognito JWT
    feed.ts               ← getFeed(), getCard() API calls
  auth/
    config.ts             ← Amplify/Cognito config (user pool ID, client ID, region)
    AuthGate.tsx          ← redirects to Cognito login if no token
  pages/
    Feed.tsx              ← the scrollable feed
    CardDetail.tsx        ← expanded single card view
  components/
    FeedCard.tsx           ← the card in the list (hook + why_you_now + badge)
    CardSection.tsx        ← reusable collapsible section (gist, key_ideas, etc.)
    Glossary.tsx           ← term definitions list
    MathNote.tsx           ← plain text + optional tap-to-reveal equation
    HypothesisBadge.tsx    ← "supports/refutes/refines" indicator
  index.css               ← Tailwind imports
```

---

## API contract (what the frontend calls)

**GET /feed?limit=20&lastKey=...**
```json
{
  "cards": [
    {
      "card_id": "20260615_023000_a1b2c3d4",
      "paper_id": "2304.03442",
      "hook": "You built this cold two years ago...",
      "why_you_now": "This is the formal version...",
      "time_estimate": "18 min",
      "card_type": "new_paper",
      "created_at": "2026-06-15T02:30:00Z"
    }
  ],
  "lastKey": "..." | null
}
```

**GET /feed/{card_id}**
```json
{
  "card_id": "...",
  "paper_id": "...",
  "source_url": "https://arxiv.org/abs/2304.03442",
  "hook": "...",
  "why_you_now": "...",
  "time_estimate": "18 min",
  "card_type": "new_paper",
  "digest": {
    "gist": "...",
    "key_ideas": ["...", "...", "..."],
    "deep": "..."
  },
  "glossary": [{"term": "reflection", "plain": "..."}],
  "math_notes": [{"plain": "...", "equation_optional": "..."}],
  "hypothesis_relevance": "Supports the bet...",
  "honesty_note": "Landmark paper...",
  "suggested_questions": ["...", "..."]
}
```

---

## Implementation steps (ordered)

| # | Step | What to do | Done when |
|---|---|---|---|
| D1 | Scaffold React + Vite + Tailwind | `npm create vite@latest frontend -- --template react-ts`, add Tailwind, verify dev server runs | `localhost:5173` shows a page |
| D2 | Auth setup | Install `@aws-amplify/auth`, configure with Cognito pool/client IDs, create AuthGate component that redirects to hosted UI if no session | Can log in via Cognito hosted UI and see a "logged in" message |
| D3 | Create Cognito user | Use AWS CLI to create your user in the pool (admin-create-user) | Can log in with email/password |
| D4 | API client | Create fetch wrapper that attaches the Cognito JWT to Authorization header, configure API base URL | Calling GET /feed from browser console returns data (or 401 if no cards yet) |
| D5 | Feed page | Implement Feed.tsx: calls GET /feed, renders list of FeedCard components, handles loading/empty/error states | Shows cards (or "no cards yet" placeholder) |
| D6 | FeedCard component | Card in the list: shows hook (bold, large), why_you_now (muted), time_estimate badge, card_type indicator. Taps navigate to detail. | Cards are visually appealing and tappable |
| D7 | CardDetail page | Full expanded view: all sections (gist, key_ideas, glossary, math_notes with reveal, hypothesis_relevance, honesty_note, questions, source link). Collapsible sections. | All digest content visible with progressive disclosure |
| D8 | Mobile styling | Ensure responsive: cards full-width on mobile, readable font sizes, comfortable tap targets, dark mode support | Looks good on iPhone Safari |
| D9 | Build + deploy to S3 | `npm run build`, upload dist/ to S3 bucket, configure CloudFront to serve index.html for all routes (SPA routing) | Live URL works on phone |
| D10 | Scroll on phone | Open URL on your phone. Log in. Scroll. **Does this beat Twitter?** | You answer yes/no |

---

## Visual design principles (not a design system — just taste)

1. **Cards are the only content.** No sidebars, no navigation chrome, no distractions. The feed IS the page.
2. **The hook is the hero.** Large, bold, max 2-3 lines. Everything else is secondary.
3. **Dark mode by default.** You're scrolling at night. White text on dark bg. Easy on the eyes.
4. **Generous whitespace between cards.** Each card should feel like a tweet — scannable, not claustrophobic.
5. **No images, no avatars, no decorative elements.** Pure text. The hook earns attention on words alone.
6. **Smooth transitions.** Card expand/collapse should animate (150ms ease). Feels native, not janky.
7. **Source paper link is subtle.** Small, at the bottom. Not a CTA — you read the digest first, go to source only if you want more.

---

## What's explicitly NOT in the M0 frontend

- No engagement event logging (M1 — taps/scroll depth/dwell time)
- No "Ask a question" / chat (M1)
- No library view (M1)
- No profile/areas display (M1)
- No hypothesis tracking UI (M2)
- No weekly brief view (M2)
- No offline/PWA support (later)
- No search/filter (later)

---

## Estimated effort

| Step | Effort |
|---|---|
| D1-D3 (scaffold + auth) | ~2 hours |
| D4-D5 (API + feed page) | ~2 hours |
| D6-D8 (components + styling) | ~3-4 hours |
| D9-D10 (deploy + test) | ~1 hour |
| **Total** | **~8-10 hours** |

This is the smallest amount of frontend that proves whether the hooks work. If they do, we invest in the UI. If they don't, we fix the prompts — no frontend work wasted.
