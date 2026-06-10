"""API handler: Library reads."""

from __future__ import annotations


def handler(event: dict, context) -> dict:
    """Lambda handler for library API.

    GET /library — list all library entries, newest first
    GET /library/{paper_id} — single library entry + rewrite
    """
    raise NotImplementedError("Library API — M1 build step")
