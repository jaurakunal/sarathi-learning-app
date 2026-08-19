"""Tier 3 eval: an independent LLM relevance judge over the FULL candidate pool.

Tier 2 could only measure over SERVED papers, whose triage_score is range-
restricted (triage pre-filters to its top band). This judge scores EVERY
candidate — served or not — for topical fit to the user's profile, giving the
variance needed to actually validate the ranker.

Independence / anti-circularity (this is the whole point):
  - Uses a model DISTINCT from triage's primary (triage runs on Kimi; the judge
    defaults to Claude Sonnet). Configurable via RELEVANCE_JUDGE_MODEL.
  - A rubric prompt distinct from triage's.
  - BLIND to the triage_score and to any engagement — it is shown only the paper
    and the profile, so its verdict is not contaminated by what the pipeline
    already decided.

It is still an LLM oracle conditioned on the profile, not ground truth — treat
it as an independent second opinion, cross-checked against engagement.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

from backend.shared.llm import DEFAULT_MODEL_ID, call_llm
from backend.eval.judge import _profile_brief, _parse_judge_json

logger = logging.getLogger(__name__)

# Default to a model NOT in triage's primary path (triage = moonshotai.kimi-k2.5).
RELEVANCE_JUDGE_MODEL = os.environ.get("RELEVANCE_JUDGE_MODEL", DEFAULT_MODEL_ID)

_SYSTEM = """You are an independent relevance oracle for a research paper feed.

Given a user's research profile and a single paper, judge how well the PAPER
fits THIS user's interests, level, and intent. Judge the paper itself — you are
NOT shown, and must not consider, any prior scoring, ranking, or the user's
past behavior. Judge only topical and level/intent fit from the abstract.

Score with this rubric:
- relevance: 0.0-1.0. 1.0 = squarely on one of their areas at their level and
  intent; 0.5 = adjacent/tangential; 0.0 = unrelated or badly mismatched
  (e.g. heavy theory for a beginner who wants applied work).

Return ONLY this JSON, no prose:
{"relevance": <float 0-1>, "on_topic": <bool>, "reason": "<one sentence>"}"""


def judge_paper_relevance(
    paper: dict,
    profile: dict,
    model: Optional[str] = None,
) -> dict:
    """Judge one paper's relevance to the profile. Blind to triage/engagement.

    Returns {"relevance": float|None, "on_topic": bool, "reason": str}.
    relevance is None on any LLM/parse failure (caller filters those out).
    """
    brief = _profile_brief(profile)
    title = paper.get("title", "")
    abstract = (paper.get("abstract") or "")[:1800]
    user_message = (
        f"USER PROFILE:\n{brief}\n\n"
        f"PAPER:\nTitle: {title}\nAbstract: {abstract}\n\n"
        "Return ONLY the JSON."
    )
    raw = call_llm(
        system=_SYSTEM,
        user_message=user_message,
        model_id=model or RELEVANCE_JUDGE_MODEL,
        max_tokens=300,
        temperature=0.0,
    )
    data = _parse_judge_json(raw) if raw else None
    if not isinstance(data, dict) or "relevance" not in data:
        return {"relevance": None, "on_topic": False, "reason": ""}
    try:
        rel = max(0.0, min(1.0, float(data["relevance"])))
    except (TypeError, ValueError):
        return {"relevance": None, "on_topic": False, "reason": ""}
    return {
        "relevance": rel,
        "on_topic": bool(data.get("on_topic", rel >= 0.5)),
        "reason": str(data.get("reason", "")),
    }
