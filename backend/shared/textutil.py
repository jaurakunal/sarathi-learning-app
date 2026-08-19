"""Small shared text helpers."""

from __future__ import annotations


def flatten_field(v) -> str:
    """Render a profile field that may be a str or a dict as a compact string.

    Profile fields like learning_style / paper_preference are sometimes stored
    as a dict and sometimes a plain string; both triage and the eval judge need
    them flattened to one line. Returns "" for falsy values.
    """
    if isinstance(v, dict):
        return "; ".join(f"{k}: {val}" for k, val in v.items() if val)
    return str(v or "").strip()
