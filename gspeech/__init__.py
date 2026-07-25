"""
gspeech: text-to-speech synthesis using the Google Translate TTS API.

Key components:
- `Speech`: Handles text-to-speech processing and audio playback.
- `SpeechSegment`: Represents a segment of text-to-speech audio.
- `SpeechPlayer`: Provides interruptible, reusable audio playback.
- `PreloaderThread`: Preloads text-to-speech data for smoother playback.
- `SUPPORTED_LANGUAGES`: A list of languages supported by the Google Translate TTS API.
- `LANGUAGES_OPTIONS`: A list of dictionaries containing supported languages for
  the Google Translate TTS API. Each dictionary includes a `value` (language
  code, e.g., 'de') and a `label` (human-readable description, e.g., 'German').

Usage:
    python -m gspeech "Hello, world!" -l en
"""

from .audio import AudioBackend, MiniaudioBackend
from .cli import main as cl_main
from .config import LANGUAGES_OPTIONS, SUPPORTED_LANGUAGES
from .player import (
    SpeechHandle,
    SpeechPlayer,
    SpeechPolicy,
    SpeechResult,
    SpeechStatus,
)
from .preloader_thread import PreloaderThread
from .speech import Speech
from .speech_segment import SpeechSegment
from .version import version

__all__ = [
    "version",
    "AudioBackend",
    "MiniaudioBackend",
    "Speech",
    "SpeechHandle",
    "SpeechPlayer",
    "SpeechPolicy",
    "SpeechResult",
    "SpeechSegment",
    "SpeechStatus",
    "PreloaderThread",
    "SUPPORTED_LANGUAGES",
    "LANGUAGES_OPTIONS",
    "cl_main",
]
