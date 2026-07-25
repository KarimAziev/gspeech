"""Text normalization, segmentation, synthesis, and blocking playback helpers."""

from __future__ import annotations

import re
import string
import unicodedata
import warnings
from collections.abc import Callable, Iterator
from os import PathLike
from typing import TYPE_CHECKING, BinaryIO

from gspeech.client import GoogleTranslateTTSClient, Synthesizer
from gspeech.config import SUPPORTED_LANGUAGES, LanguageCode
from gspeech.speech_segment import SpeechSegment

if TYPE_CHECKING:
    from gspeech.player import SpeechPlayer, SpeechResult

_MULTIPLE_WHITESPACE_RE = re.compile(r"\s{2,}")


def _find_last_matching_index(
    text: str,
    predicate: Callable[[str], bool],
) -> int | None:
    for index in range(len(text) - 1, -1, -1):
        if predicate(text[index]):
            return index
    return None


def _normalize_text(text: str) -> str:
    return _MULTIPLE_WHITESPACE_RE.sub(
        " ",
        text.replace("\n", " ").replace("\t", " ").strip(),
    )


class Speech:
    """Normalized text and language that can be segmented and synthesized."""

    MAX_SEGMENT_SIZE = 200

    def __init__(self, text: str, lang: LanguageCode | str):
        if lang not in SUPPORTED_LANGUAGES:
            raise ValueError(f"Unsupported language: {lang!r}")
        self.text = _normalize_text(text)
        self.lang: LanguageCode = lang

    def __iter__(self) -> Iterator[SpeechSegment]:
        segments = self.split_text(self.text)
        for segment_num, segment in enumerate(segments):
            yield SpeechSegment(
                text=segment,
                lang=self.lang,
                segment_num=segment_num,
                segment_count=len(segments),
            )

    @classmethod
    def split_text(cls, text: str) -> list[str]:
        """Split text at natural boundaries without exceeding 200 characters."""
        segments: list[str] = []
        remaining_text = _normalize_text(text)

        while len(remaining_text) > cls.MAX_SEGMENT_SIZE:
            current_text = remaining_text[: cls.MAX_SEGMENT_SIZE]
            split_index = _find_last_matching_index(
                current_text,
                lambda character: (
                    unicodedata.category(character) in ("Ps", "Pe", "Pi", "Pf", "Po")
                ),
            )
            if split_index is None:
                split_index = _find_last_matching_index(
                    current_text,
                    lambda character: unicodedata.category(character).startswith("Z"),
                )
            if split_index is None:
                split_index = _find_last_matching_index(
                    current_text,
                    lambda character: (
                        unicodedata.category(character)[0] not in ("L", "N")
                    ),
                )
            if split_index is None:
                split_index = cls.MAX_SEGMENT_SIZE - 1

            segments.append(current_text[: split_index + 1].rstrip())
            remaining_text = remaining_text[split_index + 1 :].lstrip(
                string.whitespace + string.punctuation
            )

        if remaining_text:
            segments.append(remaining_text)
        return segments

    def play(self, player: SpeechPlayer | None = None) -> SpeechResult:
        """
        Play the text synchronously and return its final result.

        Pass a shared player when another thread may interrupt or replace the request.
        """
        from gspeech.player import SpeechPlayer

        owns_player = player is None
        active_player = player or SpeechPlayer()
        try:
            result = active_player.play(self)
            result.raise_for_error()
            return result
        finally:
            if owns_player:
                active_player.close()

    def save(
        self,
        path: str | bytes | PathLike[str] | PathLike[bytes] | int,
        *,
        synthesizer: Synthesizer | None = None,
    ) -> None:
        """Synthesize and save concatenated MP3 segment data to a path."""
        with open(path, "wb") as output:
            self.write_to(output, synthesizer=synthesizer)

    def write_to(
        self,
        file: BinaryIO,
        *,
        synthesizer: Synthesizer | None = None,
    ) -> None:
        """Synthesize and write concatenated MP3 segment data to a binary stream."""
        owns_synthesizer = synthesizer is None
        active_synthesizer = synthesizer or GoogleTranslateTTSClient()
        try:
            for segment in self:
                file.write(active_synthesizer.synthesize(segment.text, segment.lang))
        finally:
            if owns_synthesizer:
                active_synthesizer.close()

    def savef(self, file: BinaryIO) -> None:
        """Deprecated alias for :meth:`write_to`."""
        warnings.warn(
            "Speech.savef() is deprecated; use Speech.write_to()",
            DeprecationWarning,
            stacklevel=2,
        )
        self.write_to(file)
