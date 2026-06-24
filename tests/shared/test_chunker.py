"""Unit tests for backend.shared.chunker — section-based paper chunking."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.shared import chunker


# ---------------------------------------------------------------------------
# chunk_paper_into_sections (use_llm=False)
# ---------------------------------------------------------------------------


class TestChunkPaperIntoSections:
    def test_finds_markdown_heading_sections(self):
        text = (
            "# Introduction\n"
            + "A" * 200
            + "\n# Method\n"
            + "B" * 200
            + "\n# Results\n"
            + "C" * 200
            + "\n# Discussion\n"
            + "D" * 200
        )

        result = chunker.chunk_paper_into_sections(
            full_text=text,
            paper_title="Test Paper",
            paper_id="p1",
            use_llm=False,
        )

        # Should find at least 3 sections (regex threshold)
        assert len(result) >= 3
        # Each chunk should have the expected fields
        for chunk in result:
            assert "chunk_text" in chunk
            assert "section_name" in chunk
            assert chunk["paper_id"] == "p1"
            assert chunk["paper_title"] == "Test Paper"

    def test_context_prefix_prepended(self):
        text = (
            "# Introduction\n"
            + "A" * 200
            + "\n# Method\n"
            + "B" * 200
            + "\n# Results\n"
            + "C" * 200
        )

        result = chunker.chunk_paper_into_sections(
            full_text=text,
            paper_title="My Paper",
            paper_id="p1",
            use_llm=False,
        )

        for chunk in result:
            assert chunk["chunk_text"].startswith("This is the ")
            assert "My Paper" in chunk["chunk_text"]
            assert "p1" in chunk["chunk_text"]

    def test_short_sections_filtered_out(self):
        text = (
            "# Introduction\n"
            + "A" * 200
            + "\n# Tiny\n"
            + "X" * 30  # Less than 50 chars — should be filtered
            + "\n# Method\n"
            + "B" * 200
            + "\n# Results\n"
            + "C" * 200
        )

        result = chunker.chunk_paper_into_sections(
            full_text=text,
            paper_title="Test",
            paper_id="p1",
            use_llm=False,
        )

        section_names = [c["section_name"] for c in result]
        # "Tiny" section should be filtered out (text < 50 chars)
        assert "tiny" not in section_names

    @patch("backend.shared.chunker._segment_with_llm")
    def test_falls_back_to_fallback_chunk(self, mock_llm):
        """When no structure is detected, falls back to paragraph chunking."""
        # No headings, no structure
        text = "\n\n".join(["Paragraph " + "x" * 500 for _ in range(10)])
        mock_llm.return_value = []

        result = chunker.chunk_paper_into_sections(
            full_text=text,
            paper_title="Test",
            paper_id="p1",
            use_llm=True,
        )

        assert len(result) > 0
        # Fallback sections are named section_0, section_1, etc.
        assert result[0]["section_name"].startswith("section_")


# ---------------------------------------------------------------------------
# _segment_with_regex
# ---------------------------------------------------------------------------


class TestSegmentWithRegex:
    def test_markdown_headings(self):
        text = (
            "# Introduction\n"
            + "A" * 200
            + "\n## Method\n"
            + "B" * 200
            + "\n### Results\n"
            + "C" * 200
        )

        result = chunker._segment_with_regex(text)

        assert len(result) >= 3
        names = [s["name"] for s in result]
        assert "introduction" in names
        assert "method" in names
        assert "results" in names

    def test_numbered_headings(self):
        text = (
            "1. Introduction\n"
            + "A" * 200
            + "\n2. Related Work\n"
            + "B" * 200
            + "\n3. Method\n"
            + "C" * 200
        )

        result = chunker._segment_with_regex(text)

        assert len(result) >= 3

    def test_all_caps_headings(self):
        text = (
            "INTRODUCTION\n"
            + "A" * 200
            + "\nMETHOD\n"
            + "B" * 200
            + "\nRESULTS\n"
            + "C" * 200
        )

        result = chunker._segment_with_regex(text)

        assert len(result) >= 3

    def test_returns_empty_if_fewer_than_3_sections(self):
        text = "# Introduction\n" + "A" * 200

        result = chunker._segment_with_regex(text)

        # Less than 3 sections — returns empty (signals to try other methods)
        assert result == []


# ---------------------------------------------------------------------------
# _fallback_chunk
# ---------------------------------------------------------------------------


class TestFallbackChunk:
    def test_chunks_by_paragraph_boundaries(self):
        # Create text with paragraphs exceeding FALLBACK_CHUNK_SIZE
        paragraphs = ["Paragraph " + "x" * 1000 for _ in range(10)]
        text = "\n\n".join(paragraphs)

        result = chunker._fallback_chunk(text)

        assert len(result) > 1
        for section in result:
            assert section["name"].startswith("section_")
            assert len(section["text"]) > 0

    def test_respects_chunk_size_boundary(self):
        # Each paragraph is ~1000 chars, boundary is 4000
        paragraphs = ["P" * 1000 for _ in range(12)]
        text = "\n\n".join(paragraphs)

        result = chunker._fallback_chunk(text)

        # Most chunks should be <= 4000 chars (plus some slack from last paragraph)
        for section in result[:-1]:  # All but last
            assert len(section["text"]) <= 5000

    def test_short_text_returns_single_chunk(self):
        text = "Short text only."

        result = chunker._fallback_chunk(text)

        assert len(result) == 1
        assert result[0]["name"] == "section_0"
        assert result[0]["text"] == "Short text only."
