"""Pure speech-segment values."""

from __future__ import annotations

from dataclasses import dataclass

from gspeech.config import LanguageCode


@dataclass(frozen=True, slots=True)
class SpeechSegment:
    """A text segment that can be synthesized independently."""

    text: str
    lang: LanguageCode
    segment_num: int
    segment_count: int

    def __str__(self) -> str:
        return self.text
