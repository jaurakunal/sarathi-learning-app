"""Core data models for Sārathi. These mirror the DDB schema."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class AreaStatus(str, Enum):
    ACTIVE = "active"
    DORMANT = "dormant"
    ARCHIVED = "archived"


class AreaRole(str, Enum):
    SPINE = "spine"
    SECONDARY = "secondary"
    SEAM = "seam"


class PaperStatus(str, Enum):
    CANDIDATE = "candidate"
    SURFACED = "surfaced"
    SKIPPED = "skipped"
    GRADUATED = "graduated"


class CardType(str, Enum):
    NEW_PAPER = "new_paper"
    RESURFACE = "resurface"
    CONNECT = "connect"
    BRAINSTORM = "brainstorm"
    REVISIT_HYPOTHESIS = "revisit_hypothesis"
    CHALLENGE = "challenge"


class EngagementAction(str, Enum):
    VIEW = "view"
    EXPAND = "expand"
    READ = "read"
    RATE = "rate"
    ASK = "ask"
    DISMISS = "dismiss"
    BOOKMARK = "bookmark"


class ConversationScope(str, Enum):
    PAPER = "paper"
    AREA = "area"
    LIBRARY = "library"


@dataclass
class Area:
    id: str
    user_id: str
    label: str
    status: AreaStatus = AreaStatus.ACTIVE
    role: AreaRole = AreaRole.SECONDARY
    links: list[str] = field(default_factory=list)
    frontier: str = ""
    too_basic: list[str] = field(default_factory=list)
    just_right: list[str] = field(default_factory=list)
    added_at: Optional[str] = None


@dataclass
class LearningStyle:
    math: str = "route-around; tap-to-reveal only; never gate"
    lead_with: str = "applied / can-I-use-this"
    tone: str = "sharp mirror, no flattery, credit at exact scope"


@dataclass
class ReadingSpeed:
    initial_idle_threshold_s: int = 60
    current_idle_threshold_s: int = 60
    avg_active_ms_per_card: Optional[int] = None
    confidence: str = "low"
    last_calibrated: Optional[str] = None


@dataclass
class HypothesisRef:
    paper_id: str
    note: str


@dataclass
class Hypothesis:
    user_id: str
    statement: str = "Brain-structure + agentic harness >> the LLM."
    status: str = "untested"
    supporting: list[HypothesisRef] = field(default_factory=list)
    refuting: list[HypothesisRef] = field(default_factory=list)
    refining: list[HypothesisRef] = field(default_factory=list)


@dataclass
class ProfileMeta:
    user_id: str
    learning_style: LearningStyle = field(default_factory=LearningStyle)
    reading_speed: ReadingSpeed = field(default_factory=ReadingSpeed)
    paper_goal: str = "Accumulate citations/claims/gaps toward my own paper."
    last_updated: Optional[str] = None


@dataclass
class Paper:
    id: str
    user_id: str
    source: str
    title: str
    authors: list[str]
    abstract: str
    url: str
    published: str
    areas_matched: list[str] = field(default_factory=list)
    triage_score: float = 0.0
    triage_reasoning: str = ""
    worth_my_hours: bool = False
    status: PaperStatus = PaperStatus.CANDIDATE
    discovered_at: Optional[str] = None


@dataclass
class GlossaryEntry:
    term: str
    plain: str


@dataclass
class MathNote:
    plain: str
    equation_optional: str = ""


@dataclass
class Digest:
    gist: str = ""
    key_ideas: list[str] = field(default_factory=list)
    deep: str = ""


@dataclass
class FeedCard:
    user_id: str
    card_id: str
    paper_id: str
    source_url: str
    full_text_s3_key: str
    card_type: CardType = CardType.NEW_PAPER
    created_at: Optional[str] = None
    hook: str = ""
    why_you_now: str = ""
    time_estimate: str = ""
    digest: Digest = field(default_factory=Digest)
    glossary: list[GlossaryEntry] = field(default_factory=list)
    math_notes: list[MathNote] = field(default_factory=list)
    hypothesis_relevance: str = ""
    honesty_note: str = ""
    suggested_questions: list[str] = field(default_factory=list)


@dataclass
class LibraryEntry:
    user_id: str
    paper_id: str
    source_url: str
    full_text_s3_key: str
    rewrite_s3_key: str = ""
    read_at: Optional[str] = None
    my_reactions: list[str] = field(default_factory=list)
    extracted_claims: list[str] = field(default_factory=list)
    potential_citation: str = ""
    divergence_notes: str = ""


@dataclass
class EngagementEvent:
    user_id: str
    ts: str
    paper_id: str
    card_id: str
    action: EngagementAction
    active_ms: int = 0
    scroll_depth_pct: int = 0
    interactions: int = 0


@dataclass
class ProfileHistoryEvent:
    user_id: str
    ts: str
    type: str
    area_id: str = ""
    reason: str = ""
    old_frontier: str = ""
    new_frontier: str = ""
    evidence: str = ""


@dataclass
class ConversationMeta:
    user_id: str
    conv_id: str
    scope: ConversationScope
    paper_id: str = ""
    created_at: Optional[str] = None
    last_active: Optional[str] = None
    full_text_s3_key: str = ""


@dataclass
class ConversationTurn:
    user_id: str
    conv_id: str
    seq: int
    request: str
    request_ts: str
    response: Optional[str] = None
    response_ts: Optional[str] = None
    citations: list[dict] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0


@dataclass
class ConversationSummary:
    user_id: str
    conv_id: str
    seq: int
    content: str
    batch_id: str
    covers: str
