"""Render a ProposalContext to markdown.

Two entry points:
  - render_bundle_md(ctx): deterministic MD "context pack". No LLM call.
    Fixed section order so callers can diff.
  - render_proposal_md(ctx): calls the LLM once with a proposal-shaped
    prompt and returns the drafted markdown.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

from backend.research.proposal_context import ProposalContext
from backend.shared.llm import call_llm_with_fallback

logger = logging.getLogger(__name__)

DEFAULT_MODEL = os.environ.get("PROPOSAL_MODEL", "moonshotai.kimi-k2.5")
FALLBACK_MODEL = "us.anthropic.claude-sonnet-4-6"

# ---------------------------------------------------------------------------
# Bundle (deterministic markdown)
# ---------------------------------------------------------------------------

def _fmt_paper(p, idx: int) -> str:
    """Render one paper block for the bundle."""
    lines = [f"### {idx}. {p.title}"]
    meta_bits = []
    if p.authors:
        # Only take first three authors — long lists add noise.
        authors = ", ".join(p.authors[:3])
        if len(p.authors) > 3:
            authors += " et al."
        meta_bits.append(authors)
    if p.source:
        meta_bits.append(p.source)
    if p.url:
        meta_bits.append(f"[link]({p.url})")
    if meta_bits:
        lines.append("*" + " · ".join(meta_bits) + "*")
    if p.hook:
        lines.append("")
        lines.append(f"**Hook:** {p.hook}")
    if p.why_you_now:
        lines.append(f"**Why you now:** {p.why_you_now}")
    if p.digest_gist:
        lines.append("")
        lines.append(p.digest_gist)
    if p.key_ideas:
        lines.append("")
        lines.append("Key ideas:")
        for k in p.key_ideas:
            lines.append(f"- {k}")
    return "\n".join(lines)


def render_bundle_md(ctx: ProposalContext) -> str:
    """Render the context pack — the primary output.

    Deterministic: same input → same output byte-for-byte (aside from
    ``generated_at`` which the caller can inject; here we timestamp at
    render time).
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    parts: list[str] = []

    heading = f"# Research context — {ctx.area_name}" if ctx.area_name else "# Research context"
    parts.append(heading)
    parts.append(f"*Generated {now} from Sārathi workspace: {ctx.workspace_name}*")
    parts.append("")

    # ---- Hypothesis
    parts.append("## Your hypothesis")
    if ctx.hypothesis_statement:
        parts.append(ctx.hypothesis_statement)
    else:
        parts.append("_No hypothesis recorded yet._")
    parts.append("")

    # ---- Area framing
    if ctx.area_description:
        parts.append("## What you're working on")
        parts.append(ctx.area_description)
        parts.append("")

    # ---- Papers
    parts.append("## Papers you've read")
    if not ctx.papers:
        parts.append("_No digested papers yet — run the pipeline or wait for the nightly run._")
    else:
        parts.append(f"_{len(ctx.papers)} papers, most recent first._")
        parts.append("")
        for i, p in enumerate(ctx.papers, start=1):
            parts.append(_fmt_paper(p, i))
            parts.append("")

    # ---- Pinned insights
    parts.append("## Pinned insights")
    if not ctx.pinned_insights:
        parts.append("_No pinned insights yet. Pin turns in paper chats to surface them here._")
    else:
        for pin in ctx.pinned_insights:
            title = pin.paper_title or "Untitled"
            parts.append(f"**{title}**")
            if pin.question:
                parts.append(f"> Q: {pin.question}")
            if pin.answer:
                # Trim absurdly long answers.
                ans = pin.answer.strip()
                if len(ans) > 800:
                    ans = ans[:800].rstrip() + "…"
                parts.append(ans)
            parts.append("")

    # ---- Recent questions
    parts.append("## What you've been asking")
    if not ctx.recent_questions:
        parts.append("_No recent questions._")
    else:
        for q in ctx.recent_questions:
            q = q.strip()
            if q:
                parts.append(f"- {q}")
    parts.append("")

    # ---- Engagement signals
    parts.append("## Reading signals")
    e = ctx.engagement
    signal_bits = []
    if e.read_fully:
        signal_bits.append(f"{e.read_fully} read fully")
    if e.bookmarked:
        signal_bits.append(f"{e.bookmarked} bookmarked")
    if e.pinned_turns:
        signal_bits.append(f"{e.pinned_turns} insights pinned")
    if e.source_clicked:
        signal_bits.append(f"{e.source_clicked} source clicks")
    if e.dismissed:
        signal_bits.append(f"{e.dismissed} dismissed")
    if e.bounced:
        signal_bits.append(f"{e.bounced} bounced")
    if signal_bits:
        parts.append("You've engaged with the feed as: " + ", ".join(signal_bits) + ".")
    else:
        parts.append("_No engagement recorded yet._")
    parts.append("")

    # ---- Profile hints (short)
    if ctx.background or ctx.learning_style:
        parts.append("## About you")
        if ctx.background:
            parts.append(f"**Background:** {ctx.background}")
        if ctx.learning_style:
            parts.append(f"**Learning style:** {ctx.learning_style}")
        parts.append("")

    # ---- Truncation notes (so the reader knows if signal was clipped)
    if ctx.truncation_notes:
        parts.append("---")
        parts.append("_Notes:_")
        for n in ctx.truncation_notes:
            parts.append(f"- {n}")
        parts.append("")

    return "\n".join(parts).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Full proposal draft (LLM-generated)
# ---------------------------------------------------------------------------

PROPOSAL_SYSTEM_PROMPT = """You are an experienced researcher helping a builder-practitioner write a research proposal.

Draft a proposal-shaped markdown document from the workspace context below. Use this structure — do not deviate:

1. **Problem** — What is the researcher trying to solve? Ground it in their hypothesis and area.
2. **Approach** — The approach they are proposing. Be concrete; if the context suggests specifics, use them.
3. **Existing research that supports it** — Cite the papers from the context, grouped by theme. Inline citations use the format `[Paper Title — Section]` where "Section" is a brief anchor like "hook" or a phrase from the key ideas.
4. **What you're combining / what's new** — What ideas from these papers are being combined; what is novel here.
5. **How this solves the problem** — Mechanistic reasoning, not marketing.
6. **Next steps** — Concrete near-term actions. 3–5 bullets.

Style rules:
- Write in the researcher's voice: first-person, direct, no marketing fluff, no hedging clichés like "in this rapidly evolving field."
- Do NOT invent papers, findings, or numbers not in the context.
- Prefer specificity over abstractions.
- If the context is thin in any section, say so explicitly — do not paper over gaps.
- Output raw markdown, no code fences around the whole thing."""


def _pack_context_for_llm(ctx: ProposalContext) -> str:
    """Give the LLM everything the bundle would have — but as raw context."""
    # Reuse the bundle renderer as the packed input.
    return render_bundle_md(ctx)


def render_proposal_md(
    ctx: ProposalContext,
    model: Optional[str] = None,
    fallback_model: Optional[str] = None,
) -> str:
    """Call the LLM once to produce a proposal-shaped draft.

    Falls back to the bundle markdown if both LLM calls fail — the user
    at least walks away with the structured context.
    """
    context_md = _pack_context_for_llm(ctx)
    user_msg = (
        "Here is the research context from a Sārathi workspace. "
        "Draft the proposal per the required structure.\n\n"
        f"{context_md}"
    )

    result = call_llm_with_fallback(
        system=PROPOSAL_SYSTEM_PROMPT,
        user_message=user_msg,
        primary_model=model or DEFAULT_MODEL,
        fallback_model=fallback_model or FALLBACK_MODEL,
        max_tokens=4096,
        temperature=0.6,
    )
    if not result:
        logger.warning("Proposal LLM call returned None — returning bundle as fallback")
        return context_md
    return result.strip() + "\n"
