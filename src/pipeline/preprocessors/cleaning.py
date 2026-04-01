"""Text cleaning preprocessor."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import replace

from pipeline.types import ParsedDocument


class CleaningPreprocessor:
    """Strip control characters and normalize whitespace."""

    def __init__(
        self,
        strip_control_chars: bool = True,
        normalize_whitespace: bool = True,
    ) -> None:
        self._strip_control = strip_control_chars
        self._normalize_ws = normalize_whitespace

    async def process(self, doc: ParsedDocument) -> ParsedDocument:
        content = doc.content

        if self._strip_control:
            content = _strip_control_chars(content)

        if self._normalize_ws:
            content = _normalize_whitespace(content)

        return replace(doc, content=content)


_KEEP_CHARS = frozenset({"\n", "\t", "\r"})


def _strip_control_chars(text: str) -> str:
    return "".join(
        ch for ch in text
        if ch in _KEEP_CHARS or unicodedata.category(ch) not in ("Cc", "Cf")
    )


def _normalize_whitespace(text: str) -> str:
    text = re.sub(r"[^\S\n]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
