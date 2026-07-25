"""Deprecated compatibility wrapper for eager speech synthesis."""

from __future__ import annotations

import logging
import threading
import warnings
from collections.abc import Iterable

from gspeech.client import GoogleTranslateTTSClient, Synthesizer
from gspeech.speech_segment import SpeechSegment

logger = logging.getLogger(__name__)


class PreloaderThread(threading.Thread):
    """Deprecated thread that synthesizes segments into the configured cache."""

    def __init__(
        self,
        segments: Iterable[SpeechSegment] = (),
        *,
        synthesizer: Synthesizer | None = None,
        **kwargs,
    ) -> None:
        warnings.warn(
            "PreloaderThread is deprecated; SpeechPlayer preloads automatically",
            DeprecationWarning,
            stacklevel=2,
        )
        super().__init__(**kwargs)
        self.segments = tuple(segments)
        self.errors: list[Exception] = []
        self._owns_synthesizer = synthesizer is None
        self._synthesizer = synthesizer or GoogleTranslateTTSClient()

    def run(self) -> None:
        try:
            for segment in self.segments:
                try:
                    self._synthesizer.synthesize(segment.text, segment.lang)
                except Exception as error:
                    self.errors.append(error)
                    logger.error(
                        "Unable to preload speech segment: lang=%s chars=%d error=%s",
                        segment.lang,
                        len(segment.text),
                        type(error).__name__,
                    )
        finally:
            if self._owns_synthesizer:
                self._synthesizer.close()
