"""Interruptible text-to-speech synthesis and playback."""

import logging

from gspeech._cache import AudioCache
from gspeech.audio import AudioBackend, MiniaudioBackend
from gspeech.client import (
    GoogleTranslateTTSClient,
    HTTPResponse,
    HTTPSession,
    Synthesizer,
)
from gspeech.config import (
    LANGUAGES_OPTIONS,
    SUPPORTED_LANGUAGES,
    LanguageCode,
    LanguageOption,
    available_languages,
)
from gspeech.exceptions import (
    GSpeechError,
    PlaybackError,
    PlayerClosedError,
    SynthesisError,
)
from gspeech.player import (
    SpeechHandle,
    SpeechPlayer,
    SpeechPolicy,
    SpeechResult,
    SpeechStatus,
)
from gspeech.speech import Speech
from gspeech.speech_segment import SpeechSegment
from gspeech.version import version

logging.getLogger(__name__).addHandler(logging.NullHandler())

__version__ = version

__all__ = [
    "LANGUAGES_OPTIONS",
    "SUPPORTED_LANGUAGES",
    "AudioBackend",
    "AudioCache",
    "GSpeechError",
    "GoogleTranslateTTSClient",
    "HTTPResponse",
    "HTTPSession",
    "LanguageCode",
    "LanguageOption",
    "MiniaudioBackend",
    "PlaybackError",
    "PlayerClosedError",
    "Speech",
    "SpeechHandle",
    "SpeechPlayer",
    "SpeechPolicy",
    "SpeechResult",
    "SpeechSegment",
    "SpeechStatus",
    "SynthesisError",
    "Synthesizer",
    "__version__",
    "available_languages",
]
