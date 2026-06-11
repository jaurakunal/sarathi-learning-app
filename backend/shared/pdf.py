"""Shared PDF text extraction using pypdf (pure Python, no C dependencies)."""

from __future__ import annotations

import io
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def extract_text_from_pdf(pdf_bytes: bytes) -> Optional[str]:
    """Extract text from PDF bytes using pypdf.

    Returns the extracted text, or None if extraction fails or produces empty output.
    """
    try:
        from pypdf import PdfReader
    except ImportError:
        logger.error("pypdf is not installed. Add 'pypdf' to requirements.txt.")
        return None

    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        pages_text: list[str] = []

        for page in reader.pages:
            text = page.extract_text()
            if text:
                pages_text.append(text)

        full_text = "\n\n".join(pages_text)

        if not full_text.strip():
            logger.warning("PDF text extraction produced empty result")
            return None

        return full_text

    except Exception:
        logger.exception("Failed to extract text from PDF")
        return None
