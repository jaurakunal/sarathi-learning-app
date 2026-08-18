"""Tests for the EMF metrics helper."""

from __future__ import annotations

import json

from backend.shared import metrics


def _capture(capsys):
    out = capsys.readouterr().out.strip()
    return json.loads(out) if out else None


def test_emit_basic_no_dimensions(capsys):
    metrics.emit("FeedCardsGenerated", 5)
    emf = _capture(capsys)
    assert emf["FeedCardsGenerated"] == 5
    cw = emf["_aws"]["CloudWatchMetrics"][0]
    assert cw["Namespace"] == "Sarathi"
    assert cw["Metrics"][0] == {"Name": "FeedCardsGenerated", "Unit": "Count"}
    assert cw["Dimensions"] == [[]]


def test_emit_with_dimensions(capsys):
    metrics.emit("LlmCallFailed", 1, dimensions={"step": "triage", "model": "kimi"})
    emf = _capture(capsys)
    assert emf["LlmCallFailed"] == 1
    assert emf["step"] == "triage"
    assert emf["model"] == "kimi"
    dims = emf["_aws"]["CloudWatchMetrics"][0]["Dimensions"][0]
    assert set(dims) == {"step", "model"}


def test_emit_invalid_unit_falls_back_to_none(capsys):
    metrics.emit("X", 1, unit="Furlongs")
    emf = _capture(capsys)
    assert emf["_aws"]["CloudWatchMetrics"][0]["Metrics"][0]["Unit"] == "None"


def test_emit_properties_not_metricized(capsys):
    metrics.emit("Y", 2, dimensions={"a": "1"}, properties={"user_id": "u1"})
    emf = _capture(capsys)
    assert emf["user_id"] == "u1"
    # user_id must NOT be a dimension
    assert "user_id" not in emf["_aws"]["CloudWatchMetrics"][0]["Dimensions"][0]


def test_emit_never_raises_on_bad_value(capsys):
    # Non-serializable value should be swallowed, not raised.
    class Bad:
        pass
    metrics.emit("Z", Bad())  # type: ignore[arg-type]
    # No exception = pass; nothing asserted about output.


def test_emit_drops_none_dimensions(capsys):
    metrics.emit("W", 1, dimensions={"a": "x", "b": None})
    emf = _capture(capsys)
    dims = emf["_aws"]["CloudWatchMetrics"][0]["Dimensions"][0]
    assert dims == ["a"]
    assert "b" not in emf
