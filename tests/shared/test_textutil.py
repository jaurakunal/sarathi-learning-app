"""Tests for backend.shared.textutil.flatten_field."""

from __future__ import annotations

from backend.shared.textutil import flatten_field


def test_flatten_string():
    assert flatten_field("theory-first") == "theory-first"
    assert flatten_field("  padded  ") == "padded"


def test_flatten_dict():
    out = flatten_field({"math": "route-around", "lead_with": "applied"})
    assert "math: route-around" in out
    assert "lead_with: applied" in out
    assert "; " in out


def test_flatten_dict_skips_empty_values():
    assert flatten_field({"a": "x", "b": ""}) == "a: x"


def test_flatten_none_and_empty():
    assert flatten_field(None) == ""
    assert flatten_field("") == ""
    assert flatten_field({}) == ""
