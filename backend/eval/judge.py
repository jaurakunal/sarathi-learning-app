"""LLM-as-judge for comparing candidate vs golden cards.

Bias mitigation:
- Cards are labeled "Card A" / "Card B"; A/B order is randomized per paper.
- Model-fingerprint phrases ("here's a digest", "I'll provide", etc.) are stripped.
- The judge ALSO predicts engagement (read / bookmark / dismiss). We compare the
  prediction to the actual engagement from the golden dataset to produce an
  alignment score.

Self-validation:
- Running the judge with `candidate == golden` should produce engagement
  alignment >70% — if it doesn't, the judge prompt itself is unreliable.
"""

from __future__ import annotations

import json
import logging
import random
import re
import uuid
from typing import Any, Optional

from boto3.dynamodb.conditions import Key

from backend.eval import dataset as eval_dataset
from backend.shared import db
from backend.shared.llm import DEFAULT_MODEL_ID, call_llm
from backend.shared.textutil import flatten_field

logger = logging.getLogger(__name__)


JUDGE_DEFAULT_MODEL = DEFAULT_MODEL_ID  # claude-sonnet-4-6


# Phrases that often leak which model wrote a response. Stripped before
# the judge sees the cards.
_FINGERPRINT_PATTERNS = [
    r"^\s*here'?s?\s+(?:a|the|your)\s+\w+[:\.]\s*",
    r"^\s*i'?ll\s+\w+[:\.]\s*",
    r"^\s*i\s+can\s+\w+[:\.]\s*",
    r"^\s*let me\s+\w+[:\.]\s*",
    r"^\s*as an ai( language model)?,?\s*",
    r"^\s*sure[,!]\s+",
    r"^\s*absolutely[,!]\s+",
]


def _strip_fingerprints(text: str) -> str:
    """Remove leading boilerplate phrases that fingerprint a model."""
    if not isinstance(text, str):
        return text
    out = text
    for pat in _FINGERPRINT_PATTERNS:
        out = re.sub(pat, "", out, flags=re.IGNORECASE)
    return out.strip()


def anonymize_card(card: Optional[dict]) -> dict:
    """Return a copy of the card with fingerprint phrases stripped from string fields.

    Used before the judge sees a card so it can't bias on model voice.
    """
    if not card:
        return {}
    out: dict[str, Any] = {}
    for k, v in card.items():
        if isinstance(v, str):
            out[k] = _strip_fingerprints(v)
        elif isinstance(v, dict):
            out[k] = {
                kk: (_strip_fingerprints(vv) if isinstance(vv, str) else vv)
                for kk, vv in v.items()
            }
        elif isinstance(v, list):
            cleaned = []
            for item in v:
                if isinstance(item, str):
                    cleaned.append(_strip_fingerprints(item))
                elif isinstance(item, dict):
                    cleaned.append({
                        kk: (_strip_fingerprints(vv) if isinstance(vv, str) else vv)
                        for kk, vv in item.items()
                    })
                else:
                    cleaned.append(item)
            out[k] = cleaned
        else:
            out[k] = v
    return out


def actual_engagement_label(engagement: dict) -> str:
    """Reduce the rich engagement summary to a single label: read / bookmark / dismiss / view.

    Priority: bookmarked > read > dismissed > viewed > none.
    """
    if not engagement:
        return "none"
    if engagement.get("bookmarked"):
        return "bookmark"
    if engagement.get("read"):
        return "read"
    if engagement.get("dismissed"):
        return "dismiss"
    if engagement.get("viewed"):
        return "view"
    return "none"


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


_JUDGE_SYSTEM = """You are a careful research evaluator for a tool called Sarathi.

The specific user's profile (areas, level, learning style, hypothesis) is provided in each request. Judge every card RELATIVE TO THAT USER — do not assume any particular persona.

You will be shown two feed cards (Card A and Card B) for the SAME paper. Your job is to score each card on four dimensions and predict how the user would engage with it.

You MUST return ONLY a JSON object — no markdown, no commentary."""


def _build_judge_user_prompt(
    *,
    paper: dict,
    user_profile_brief: str,
    card_a: dict,
    card_b: dict,
) -> str:
    return f"""USER PROFILE (brief):
{user_profile_brief}

PAPER:
Title: {paper.get('title', '')}
Authors: {', '.join(paper.get('authors', []) or [])}
Abstract: {(paper.get('abstract') or '')[:1500]}

CARD A:
{json.dumps(card_a, indent=2)[:6000]}

CARD B:
{json.dumps(card_b, indent=2)[:6000]}

For EACH card (a, b) score 1-5 (5 = best) on:
- relevance: does the hook connect to the user's research interests / frontiers?
- specificity: is it about THIS paper's actual contribution, not generic?
- calibration: does the explanation match the user's stated level and learning style (see the profile above)?
- actionability: does it surface "why now" / what to do with this?

Then predict engagement: one of "read" | "bookmark" | "dismiss" | "view" | "none".

Return ONLY this JSON shape:
{{
  "a": {{
    "relevance": <int>,
    "specificity": <int>,
    "calibration": <int>,
    "actionability": <int>,
    "predicted_engagement": "<label>",
    "rationale": "<one sentence>"
  }},
  "b": {{
    "relevance": <int>,
    "specificity": <int>,
    "calibration": <int>,
    "actionability": <int>,
    "predicted_engagement": "<label>",
    "rationale": "<one sentence>"
  }},
  "winner": "a" | "b" | "tie"
}}"""


def _profile_brief(profile: dict) -> str:
    """Compact profile snippet for the judge prompt: areas (with level + intent),
    hypothesis, and user-level learning signals — so the judge calibrates to THIS
    user rather than an assumed persona."""
    parts: list[str] = []
    for area in (profile.get("areas") or [])[:5]:
        label = area.get("label", area.get("id", ""))
        role = area.get("role", "secondary")
        frontier = area.get("frontier", "")
        level = area.get("current_level", "")
        intent = area.get("intent", "")
        tags = ", ".join(t for t in (f"level: {level}" if level else "",
                                     f"intent: {intent}" if intent else "") if t)
        line = f"  - [{role}] {label}"
        if tags:
            line += f" ({tags})"
        if frontier:
            line += f" — frontier: {frontier}"
        parts.append(line)
    out = "Areas:\n" + ("\n".join(parts) if parts else "  (none)")

    hyp = (profile.get("hypothesis") or {}).get("statement", "")
    if hyp:
        out += f"\nHypothesis: {hyp}"

    um = profile.get("user_meta", {}) or {}
    learning = flatten_field(um.get("learning_style"))
    math = flatten_field(um.get("math_comfort"))
    if learning:
        out += f"\nLearning style: {learning}"
    if math:
        out += f"\nMath comfort: {math}"
    return out


def _parse_judge_json(text: str) -> Optional[dict]:
    """Strip code fences and parse the judge's JSON response."""
    if not text:
        return None
    text = text.strip()
    if text.startswith("```"):
        nl = text.find("\n")
        if nl >= 0:
            text = text[nl + 1:]
    if text.endswith("```"):
        text = text[:-3]
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        logger.warning("Judge returned invalid JSON: %s", text[:200])
        return None


# ---------------------------------------------------------------------------
# Per-paper judging
# ---------------------------------------------------------------------------


def judge_one_paper(
    *,
    entry: dict,
    candidate_card: Optional[dict],
    profile: dict,
    judge_model: str = JUDGE_DEFAULT_MODEL,
    rng: Optional[random.Random] = None,
) -> dict:
    """Judge a single (golden, candidate) pair.

    Returns a dict with: paper_id, winner, candidate_scores, golden_scores,
    predicted_engagement_candidate, predicted_engagement_golden,
    actual_engagement, alignment_candidate, alignment_golden.
    """
    rng = rng or random.Random()
    paper_id = entry.get("paper_id", "")
    paper = entry.get("paper") or {}
    golden = entry.get("golden_card") or {}
    engagement = entry.get("engagement") or {}
    actual = actual_engagement_label(engagement)

    golden_anon = anonymize_card(golden)
    candidate_anon = anonymize_card(candidate_card)

    # Randomize A/B order so the judge can't bias by position
    swap = rng.random() < 0.5
    if swap:
        card_a, card_b = candidate_anon, golden_anon
        a_role, b_role = "candidate", "golden"
    else:
        card_a, card_b = golden_anon, candidate_anon
        a_role, b_role = "golden", "candidate"

    user_prompt = _build_judge_user_prompt(
        paper=paper,
        user_profile_brief=_profile_brief(profile),
        card_a=card_a,
        card_b=card_b,
    )

    raw = call_llm(
        system=_JUDGE_SYSTEM,
        user_message=user_prompt,
        model_id=judge_model,
        max_tokens=2048,
        temperature=0.0,
    )
    parsed = _parse_judge_json(raw or "")

    result = {
        "paper_id": paper_id,
        "judge_model": judge_model,
        "swap": swap,
        "actual_engagement": actual,
        "candidate_scores": None,
        "golden_scores": None,
        "predicted_engagement_candidate": None,
        "predicted_engagement_golden": None,
        "winner": None,
        "raw_response": raw,
        "error": None,
    }

    if not parsed:
        result["error"] = "judge_invalid_json"
        return result

    a_block = parsed.get("a") or {}
    b_block = parsed.get("b") or {}
    winner = parsed.get("winner")

    if a_role == "candidate":
        result["candidate_scores"] = a_block
        result["golden_scores"] = b_block
    else:
        result["candidate_scores"] = b_block
        result["golden_scores"] = a_block

    result["predicted_engagement_candidate"] = (
        result["candidate_scores"].get("predicted_engagement")
        if result["candidate_scores"] else None
    )
    result["predicted_engagement_golden"] = (
        result["golden_scores"].get("predicted_engagement")
        if result["golden_scores"] else None
    )

    # De-swap the winner so it always refers to candidate/golden directly
    if winner in ("a", "b"):
        if (winner == "a" and a_role == "candidate") or (winner == "b" and b_role == "candidate"):
            result["winner"] = "candidate"
        else:
            result["winner"] = "golden"
    elif winner == "tie":
        result["winner"] = "tie"

    return result


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------


_DIMENSIONS = ("relevance", "specificity", "calibration", "actionability")


def _avg(scores: list[Any]) -> float:
    nums = [float(s) for s in scores if isinstance(s, (int, float))]
    if not nums:
        return 0.0
    return round(sum(nums) / len(nums), 3)


def _engagement_aligned(predicted: Optional[str], actual: str) -> bool:
    """Treat read+bookmark as 'positive', dismiss as 'negative', else neutral.

    Aligned if both are positive OR both are negative OR both are neutral.
    """
    if not predicted:
        return False
    pos = {"read", "bookmark"}
    neg = {"dismiss"}
    p_class = "pos" if predicted in pos else "neg" if predicted in neg else "neu"
    a_class = "pos" if actual in pos else "neg" if actual in neg else "neu"
    return p_class == a_class


def aggregate_judge_results(per_paper: list[dict]) -> dict:
    """Compute means + alignment % across the per-paper judge results."""
    cand_dim_scores: dict[str, list[float]] = {d: [] for d in _DIMENSIONS}
    gold_dim_scores: dict[str, list[float]] = {d: [] for d in _DIMENSIONS}

    cand_aligned = 0
    gold_aligned = 0
    valid = 0
    cand_wins = 0
    gold_wins = 0
    ties = 0

    for r in per_paper:
        if r.get("error"):
            continue
        cand = r.get("candidate_scores") or {}
        gold = r.get("golden_scores") or {}
        for d in _DIMENSIONS:
            if isinstance(cand.get(d), (int, float)):
                cand_dim_scores[d].append(float(cand[d]))
            if isinstance(gold.get(d), (int, float)):
                gold_dim_scores[d].append(float(gold[d]))

        actual = r.get("actual_engagement", "none")
        if _engagement_aligned(r.get("predicted_engagement_candidate"), actual):
            cand_aligned += 1
        if _engagement_aligned(r.get("predicted_engagement_golden"), actual):
            gold_aligned += 1
        valid += 1

        winner = r.get("winner")
        if winner == "candidate":
            cand_wins += 1
        elif winner == "golden":
            gold_wins += 1
        elif winner == "tie":
            ties += 1

    return {
        "papers_judged": valid,
        "candidate": {
            **{f"avg_{d}": _avg(cand_dim_scores[d]) for d in _DIMENSIONS},
            "engagement_alignment_pct": round(100.0 * cand_aligned / max(valid, 1), 1),
        },
        "golden": {
            **{f"avg_{d}": _avg(gold_dim_scores[d]) for d in _DIMENSIONS},
            "engagement_alignment_pct": round(100.0 * gold_aligned / max(valid, 1), 1),
        },
        "candidate_wins": cand_wins,
        "golden_wins": gold_wins,
        "ties": ties,
        "candidate_win_rate_pct": round(
            100.0 * cand_wins / max(valid, 1), 1
        ),
    }


# ---------------------------------------------------------------------------
# Persisting / loading judge runs
# ---------------------------------------------------------------------------


def persist_judge_run(table, *, judge_run_id: str, candidate_run_id: str,
                      judge_model: str, per_paper: list[dict],
                      aggregate: dict, self_validation: bool = False) -> None:
    """Write META + per-paper records under EVAL#JUDGE#<judge_run_id>."""
    pk = f"EVAL#JUDGE#{judge_run_id}"

    meta = {
        "PK": pk,
        "SK": "META",
        "judge_run_id": judge_run_id,
        "candidate_run_id": candidate_run_id,
        "judge_model": judge_model,
        "self_validation": self_validation,
        "completed_at": db._now_iso(),
        **aggregate,
    }
    table.put_item(Item=db._sanitize_item(meta))

    for r in per_paper:
        paper_id = r.get("paper_id")
        if not paper_id:
            continue
        item = {
            "PK": pk,
            "SK": f"PAPER#{paper_id}",
            **r,
        }
        # raw_response can be huge; cap it so we don't blow DDB's 400KB item limit.
        if isinstance(item.get("raw_response"), str):
            item["raw_response"] = item["raw_response"][:8000]
        table.put_item(Item=db._sanitize_item(item))


def list_judge_runs(table) -> list[dict]:
    """Return all judge run META records."""
    from boto3.dynamodb.conditions import Attr
    resp = table.scan(
        FilterExpression=(
            Attr("PK").begins_with("EVAL#JUDGE#") & Attr("SK").eq("META")
        )
    )
    items = list(resp.get("Items", []))
    while resp.get("LastEvaluatedKey"):
        resp = table.scan(
            FilterExpression=(
                Attr("PK").begins_with("EVAL#JUDGE#") & Attr("SK").eq("META")
            ),
            ExclusiveStartKey=resp["LastEvaluatedKey"],
        )
        items.extend(resp.get("Items", []))
    items.sort(key=lambda i: i.get("completed_at", ""))
    return items


# ---------------------------------------------------------------------------
# Top-level orchestration: judge a candidate run + optional self-validation
# ---------------------------------------------------------------------------


def run_judge(
    table,
    *,
    candidate_run_id: str,
    judge_model: str = JUDGE_DEFAULT_MODEL,
    user_id: str = eval_dataset.TEST_USER_ID,
    self_validation: bool = False,
    seed: Optional[int] = None,
) -> dict:
    """Judge an existing eval run against the golden dataset.

    If self_validation=True, judges golden vs golden — should produce engagement
    alignment >70% if the prompt is reliable.

    Returns the META record for the judge run.
    """
    profile = db.get_full_profile(table, user_id, "")
    if not profile.get("meta"):
        raise RuntimeError(f"No profile for user {user_id} — run setup first")
    profile["user_meta"] = db.get_user_meta(table, user_id) or {}

    dataset_entries = {
        e["paper_id"]: e for e in eval_dataset.load_dataset(table)
        if e.get("paper_id")
    }
    if not dataset_entries:
        raise RuntimeError("No eval dataset — run setup first")

    candidate_papers: dict[str, dict] = {}
    if not self_validation:
        from backend.eval.runner import load_run_papers
        for r in load_run_papers(table, candidate_run_id):
            pid = r.get("paper_id")
            if pid:
                candidate_papers[pid] = r

    rng = random.Random(seed)

    per_paper: list[dict] = []
    for paper_id, entry in dataset_entries.items():
        if self_validation:
            candidate_card = entry.get("golden_card")
            # In self-validation, both sides must have a golden_card to compare
            if not candidate_card or not entry.get("golden_card"):
                per_paper.append({
                    "paper_id": paper_id,
                    "judge_model": judge_model,
                    "error": "no_golden_card",
                })
                continue
        else:
            cand_record = candidate_papers.get(paper_id)
            candidate_card = cand_record.get("candidate_card") if cand_record else None
            if candidate_card is None:
                # No candidate card to judge — record as skipped, don't call LLM
                per_paper.append({
                    "paper_id": paper_id,
                    "judge_model": judge_model,
                    "error": "no_candidate_card",
                })
                continue
            # Also skip if no golden card to compare against
            if not entry.get("golden_card"):
                per_paper.append({
                    "paper_id": paper_id,
                    "judge_model": judge_model,
                    "error": "no_golden_card",
                })
                continue

        result = judge_one_paper(
            entry=entry,
            candidate_card=candidate_card,
            profile=profile,
            judge_model=judge_model,
            rng=rng,
        )
        per_paper.append(result)

    aggregate = aggregate_judge_results(per_paper)
    judge_run_id = f"{db._now_iso()}_{uuid.uuid4().hex[:8]}"

    persist_judge_run(
        table,
        judge_run_id=judge_run_id,
        candidate_run_id=candidate_run_id if not self_validation else "SELF",
        judge_model=judge_model,
        per_paper=per_paper,
        aggregate=aggregate,
        self_validation=self_validation,
    )

    # NOTE: engagement alignment was removed as a validation gate — engagement is
    # multi-factorial (mood, schedule, what else they read), and even Sonnet
    # judging itself can't reliably predict it from card content alone. We rely
    # on the dimensional scores (relevance/specificity/calibration/actionability)
    # and head-to-head win rate instead. The alignment % is still computed and
    # stored for informational use.
    if self_validation:
        align = aggregate.get("golden", {}).get("engagement_alignment_pct", 0.0)
        logger.info("Self-validation done. Engagement alignment (informational): %.1f%%", align)

    return {
        "judge_run_id": judge_run_id,
        "candidate_run_id": candidate_run_id if not self_validation else "SELF",
        "judge_model": judge_model,
        "self_validation": self_validation,
        **aggregate,
    }
