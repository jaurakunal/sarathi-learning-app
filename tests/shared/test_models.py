"""Unit tests for backend.shared.models — dataclass construction, enums, asdict shapes."""

from dataclasses import asdict

import pytest

from backend.shared.models import (
    Area,
    AreaRole,
    AreaStatus,
    CardType,
    ConversationMeta,
    ConversationScope,
    ConversationSummary,
    ConversationTurn,
    Digest,
    EngagementAction,
    EngagementEvent,
    FeedCard,
    GlossaryEntry,
    Hypothesis,
    HypothesisRef,
    LearningStyle,
    LibraryEntry,
    MathNote,
    Paper,
    PaperStatus,
    ProfileHistoryEvent,
    ProfileMeta,
    ReadingSpeed,
)


# ---------------------------------------------------------------------------
# Enum tests
# ---------------------------------------------------------------------------


class TestAreaStatus:
    def test_values(self):
        assert AreaStatus.ACTIVE == "active"
        assert AreaStatus.DORMANT == "dormant"
        assert AreaStatus.ARCHIVED == "archived"

    def test_all_members(self):
        assert set(AreaStatus) == {AreaStatus.ACTIVE, AreaStatus.DORMANT, AreaStatus.ARCHIVED}

    def test_is_str(self):
        assert isinstance(AreaStatus.ACTIVE, str)


class TestAreaRole:
    def test_values(self):
        assert AreaRole.SPINE == "spine"
        assert AreaRole.SECONDARY == "secondary"
        assert AreaRole.SEAM == "seam"

    def test_all_members(self):
        assert set(AreaRole) == {AreaRole.SPINE, AreaRole.SECONDARY, AreaRole.SEAM}


class TestPaperStatus:
    def test_values(self):
        assert PaperStatus.CANDIDATE == "candidate"
        assert PaperStatus.SURFACED == "surfaced"
        assert PaperStatus.SKIPPED == "skipped"
        assert PaperStatus.GRADUATED == "graduated"

    def test_all_members(self):
        assert len(PaperStatus) == 4


class TestCardType:
    def test_values(self):
        assert CardType.NEW_PAPER == "new_paper"
        assert CardType.RESURFACE == "resurface"
        assert CardType.CONNECT == "connect"
        assert CardType.BRAINSTORM == "brainstorm"
        assert CardType.REVISIT_HYPOTHESIS == "revisit_hypothesis"
        assert CardType.CHALLENGE == "challenge"

    def test_all_members(self):
        assert len(CardType) == 6


class TestEngagementAction:
    def test_values(self):
        assert EngagementAction.VIEW == "view"
        assert EngagementAction.EXPAND == "expand"
        assert EngagementAction.READ == "read"
        assert EngagementAction.RATE == "rate"
        assert EngagementAction.ASK == "ask"
        assert EngagementAction.DISMISS == "dismiss"
        assert EngagementAction.BOOKMARK == "bookmark"

    def test_all_members(self):
        assert len(EngagementAction) == 7


class TestConversationScope:
    def test_values(self):
        assert ConversationScope.PAPER == "paper"
        assert ConversationScope.AREA == "area"
        assert ConversationScope.LIBRARY == "library"

    def test_all_members(self):
        assert len(ConversationScope) == 3


# ---------------------------------------------------------------------------
# Dataclass construction + asdict tests
# ---------------------------------------------------------------------------


class TestLearningStyle:
    def test_defaults(self):
        ls = LearningStyle()
        assert ls.math == "route-around; tap-to-reveal only; never gate"
        assert ls.lead_with == "applied / can-I-use-this"
        assert ls.tone == "sharp mirror, no flattery, credit at exact scope"

    def test_asdict(self):
        ls = LearningStyle()
        d = asdict(ls)
        assert set(d.keys()) == {"math", "lead_with", "tone"}


class TestReadingSpeed:
    def test_defaults(self):
        rs = ReadingSpeed()
        assert rs.initial_idle_threshold_s == 60
        assert rs.current_idle_threshold_s == 60
        assert rs.avg_active_ms_per_card is None
        assert rs.confidence == "low"
        assert rs.last_calibrated is None

    def test_custom_values(self):
        rs = ReadingSpeed(avg_active_ms_per_card=5000, confidence="high")
        assert rs.avg_active_ms_per_card == 5000
        assert rs.confidence == "high"


class TestArea:
    def test_construction_with_defaults(self):
        area = Area(id="test-area", user_id="u1", label="Test Area")
        assert area.status == AreaStatus.ACTIVE
        assert area.role == AreaRole.SECONDARY
        assert area.links == []
        assert area.frontier == ""
        assert area.too_basic == []
        assert area.just_right == []
        assert area.added_at is None

    def test_construction_with_all_fields(self):
        area = Area(
            id="a1",
            user_id="u1",
            label="My Area",
            status=AreaStatus.DORMANT,
            role=AreaRole.SPINE,
            links=["a2", "a3"],
            frontier="knows X",
            too_basic=["intro"],
            just_right=["advanced"],
            added_at="2026-01-01T00:00:00Z",
        )
        assert area.id == "a1"
        assert area.status == AreaStatus.DORMANT
        assert area.links == ["a2", "a3"]

    def test_asdict_shape(self):
        area = Area(id="a1", user_id="u1", label="Test")
        d = asdict(area)
        expected_keys = {
            "id", "user_id", "label", "status", "role",
            "links", "frontier", "too_basic", "just_right",
            "current_level", "intent", "added_at",
        }
        assert set(d.keys()) == expected_keys
        # Enum values serialize to their string value in asdict
        assert d["status"] == AreaStatus.ACTIVE
        # New signal fields carry sensible defaults
        assert d["current_level"] == "intermediate"
        assert d["intent"] == "consume"


class TestHypothesis:
    def test_defaults(self):
        h = Hypothesis(user_id="u1")
        assert h.statement == "Brain-structure + agentic harness >> the LLM."
        assert h.status == "untested"
        assert h.supporting == []
        assert h.refuting == []
        assert h.refining == []

    def test_with_refs(self):
        ref = HypothesisRef(paper_id="p1", note="supports claim X")
        h = Hypothesis(user_id="u1", supporting=[ref])
        d = asdict(h)
        assert len(d["supporting"]) == 1
        assert d["supporting"][0]["paper_id"] == "p1"


class TestHypothesisRef:
    def test_construction(self):
        ref = HypothesisRef(paper_id="p1", note="relevant")
        assert ref.paper_id == "p1"
        assert ref.note == "relevant"


class TestProfileMeta:
    def test_defaults(self):
        pm = ProfileMeta(user_id="u1")
        assert pm.paper_goal == "Accumulate citations/claims/gaps toward my own paper."
        assert isinstance(pm.learning_style, LearningStyle)
        assert isinstance(pm.reading_speed, ReadingSpeed)
        assert pm.last_updated is None

    def test_asdict_nested(self):
        pm = ProfileMeta(user_id="u1")
        d = asdict(pm)
        assert isinstance(d["learning_style"], dict)
        assert "math" in d["learning_style"]
        assert isinstance(d["reading_speed"], dict)
        assert "initial_idle_threshold_s" in d["reading_speed"]


class TestPaper:
    def test_construction_with_required_fields(self):
        p = Paper(
            id="p1",
            user_id="u1",
            source="arxiv",
            title="Test Paper",
            authors=["Alice"],
            abstract="An abstract",
            url="https://arxiv.org/abs/1234",
            published="2026-01-01",
        )
        assert p.status == PaperStatus.CANDIDATE
        assert p.triage_score == 0.0
        assert p.areas_matched == []
        assert p.discovered_at is None

    def test_asdict_shape(self):
        p = Paper(
            id="p1", user_id="u1", source="arxiv", title="T",
            authors=[], abstract="", url="", published="",
        )
        d = asdict(p)
        expected_keys = {
            "id", "user_id", "source", "title", "authors", "abstract", "url",
            "published", "areas_matched", "triage_score", "triage_reasoning",
            "worth_my_hours", "status", "discovered_at",
        }
        assert set(d.keys()) == expected_keys


class TestDigest:
    def test_defaults(self):
        d = Digest()
        assert d.gist == ""
        assert d.key_ideas == []
        assert d.deep == ""


class TestGlossaryEntry:
    def test_construction(self):
        ge = GlossaryEntry(term="RAG", plain="Retrieval augmented generation")
        assert ge.term == "RAG"
        assert ge.plain == "Retrieval augmented generation"


class TestMathNote:
    def test_defaults(self):
        mn = MathNote(plain="E equals mc squared")
        assert mn.equation_optional == ""


class TestFeedCard:
    def test_defaults(self):
        fc = FeedCard(
            user_id="u1",
            card_id="c1",
            paper_id="p1",
            source_url="http://example.com",
            full_text_s3_key="s3://bucket/key",
        )
        assert fc.card_type == CardType.NEW_PAPER
        assert fc.created_at is None
        assert fc.hook == ""
        assert fc.digest == Digest()
        assert fc.glossary == []
        assert fc.math_notes == []
        assert fc.suggested_questions == []

    def test_asdict_nested_structures(self):
        fc = FeedCard(
            user_id="u1", card_id="c1", paper_id="p1",
            source_url="", full_text_s3_key="",
            glossary=[GlossaryEntry(term="x", plain="y")],
            math_notes=[MathNote(plain="z")],
        )
        d = asdict(fc)
        assert d["glossary"] == [{"term": "x", "plain": "y"}]
        assert d["math_notes"] == [{"plain": "z", "equation_optional": ""}]


class TestLibraryEntry:
    def test_defaults(self):
        le = LibraryEntry(
            user_id="u1", paper_id="p1",
            source_url="http://example.com", full_text_s3_key="s3://k",
        )
        assert le.rewrite_s3_key == ""
        assert le.read_at is None
        assert le.my_reactions == []
        assert le.extracted_claims == []
        assert le.potential_citation == ""
        assert le.divergence_notes == ""


class TestEngagementEvent:
    def test_construction(self):
        ee = EngagementEvent(
            user_id="u1", ts="2026-06-10T00:00:00Z",
            paper_id="p1", card_id="c1",
            action=EngagementAction.VIEW,
        )
        assert ee.active_ms == 0
        assert ee.scroll_depth_pct == 0
        assert ee.interactions == 0


class TestProfileHistoryEvent:
    def test_construction(self):
        phe = ProfileHistoryEvent(
            user_id="u1", ts="2026-06-10T00:00:00Z", type="area_added",
        )
        assert phe.area_id == ""
        assert phe.reason == ""
        assert phe.old_frontier == ""
        assert phe.new_frontier == ""
        assert phe.evidence == ""


class TestConversationMeta:
    def test_construction(self):
        cm = ConversationMeta(
            user_id="u1", conv_id="conv1", scope=ConversationScope.PAPER,
        )
        assert cm.paper_id == ""
        assert cm.created_at is None
        assert cm.last_active is None
        assert cm.full_text_s3_key == ""


class TestConversationTurn:
    def test_construction(self):
        ct = ConversationTurn(
            user_id="u1", conv_id="conv1", seq=1,
            request="hello", request_ts="2026-06-10T00:00:00Z",
        )
        assert ct.response is None
        assert ct.response_ts is None
        assert ct.citations == []
        assert ct.tokens_in == 0
        assert ct.tokens_out == 0

    def test_asdict(self):
        ct = ConversationTurn(
            user_id="u1", conv_id="conv1", seq=1,
            request="hello", request_ts="ts1",
        )
        d = asdict(ct)
        expected_keys = {
            "user_id", "conv_id", "seq", "request", "request_ts",
            "response", "response_ts", "citations", "tokens_in", "tokens_out",
        }
        assert set(d.keys()) == expected_keys


class TestConversationSummary:
    def test_construction(self):
        cs = ConversationSummary(
            user_id="u1", conv_id="conv1", seq=5,
            content="summary text", batch_id="b1", covers="1-5",
        )
        assert cs.content == "summary text"
        assert cs.batch_id == "b1"
        assert cs.covers == "1-5"
