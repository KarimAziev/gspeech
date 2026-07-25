"""Google Translate speech synthesis client."""

from __future__ import annotations

import hashlib
import logging
import sqlite3
import threading
import urllib.parse
from collections.abc import Callable, Mapping
from os import PathLike
from pathlib import Path
from typing import Any, Protocol, cast

import requests
from platformdirs import user_cache_path

from gspeech._cache import AudioCache, NullAudioCache, SQLiteAudioCache
from gspeech.exceptions import PlayerClosedError, SynthesisError

logger = logging.getLogger(__name__)

_PROVIDER_CACHE_VERSION = b"google-translate-tts-v1"
_DEFAULT_CACHE_TTL_SECONDS = 60 * 60 * 24 * 365
_DEFAULT_CACHE_MAX_ENTRIES = 2_000
_DEFAULT_TIMEOUT = (3.05, 5.0)


class Synthesizer(Protocol):
    """Synchronous encoded-audio synthesizer used by :class:`SpeechPlayer`."""

    def synthesize(self, text: str, lang: str) -> bytes:
        """Return encoded audio for one text segment."""
        ...

    def close(self) -> None:
        """Release resources owned by the synthesizer."""
        ...


class HTTPResponse(Protocol):
    """Minimal HTTP response interface required by the synthesis client."""

    @property
    def content(self) -> bytes:
        """Return response bytes."""
        ...

    @property
    def headers(self) -> Mapping[str, str]:
        """Return response headers."""
        ...

    def raise_for_status(self) -> None:
        """Raise when the response status is unsuccessful."""
        ...


class HTTPSession(Protocol):
    """Minimal per-thread HTTP session interface used for dependency injection."""

    def get(self, url: str, **kwargs: Any) -> HTTPResponse:
        """Perform an HTTP GET request."""
        ...

    def close(self) -> None:
        """Close the session."""
        ...


class GoogleTranslateTTSClient:
    """Synthesize MP3 audio with Google Translate's undocumented TTS endpoint."""

    BASE_URL = "https://translate.google.com/translate_tts"

    def __init__(
        self,
        *,
        cache_enabled: bool = True,
        cache_dir: str | PathLike[str] | None = None,
        cache_ttl_seconds: float = _DEFAULT_CACHE_TTL_SECONDS,
        cache_max_entries: int = _DEFAULT_CACHE_MAX_ENTRIES,
        timeout: tuple[float, float] = _DEFAULT_TIMEOUT,
        cache: AudioCache | None = None,
        session_factory: Callable[[], HTTPSession] | None = None,
    ) -> None:
        connect_timeout, read_timeout = timeout
        if connect_timeout <= 0 or read_timeout <= 0:
            raise ValueError("timeout values must be greater than zero")

        self.timeout = timeout
        self._session_factory = session_factory or cast(
            Callable[[], HTTPSession],
            requests.Session,
        )
        self._thread_local = threading.local()
        self._sessions: list[HTTPSession] = []
        self._lock = threading.Lock()
        self._closed = False
        self._cache = (
            cache
            if cache is not None
            else self._create_default_cache(
                cache_enabled=cache_enabled,
                cache_dir=cache_dir,
                ttl_seconds=cache_ttl_seconds,
                max_entries=cache_max_entries,
            )
        )

    def __enter__(self) -> GoogleTranslateTTSClient:
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    @staticmethod
    def _create_default_cache(
        *,
        cache_enabled: bool,
        cache_dir: str | PathLike[str] | None,
        ttl_seconds: float,
        max_entries: int,
    ) -> AudioCache:
        if not cache_enabled:
            return NullAudioCache()

        try:
            root = (
                Path(cache_dir)
                if cache_dir is not None
                else user_cache_path("gspeech", ensure_exists=True)
            )
            return SQLiteAudioCache(
                root / "audio-cache.sqlite3",
                ttl_seconds=ttl_seconds,
                max_entries=max_entries,
            )
        except (OSError, sqlite3.Error):
            logger.warning(
                "Persistent speech cache is unavailable; continuing without it",
                exc_info=True,
            )
            return NullAudioCache()

    def _get_session(self) -> HTTPSession:
        session = getattr(self._thread_local, "session", None)
        if session is not None:
            return session

        with self._lock:
            if self._closed:
                raise PlayerClosedError("Speech synthesizer is closed")
            session = self._session_factory()
            self._sessions.append(session)
            self._thread_local.session = session
            return session

    @classmethod
    def _build_url(cls, text: str, lang: str) -> str:
        parameters = {
            "client": "tw-ob",
            "ie": "UTF-8",
            "idx": "0",
            "total": "1",
            "textlen": str(len(text)),
            "tl": lang,
            "q": text,
        }
        return f"{cls.BASE_URL}?{urllib.parse.urlencode(parameters)}"

    @staticmethod
    def _cache_key(text: str, lang: str) -> str:
        digest = hashlib.sha256()
        digest.update(_PROVIDER_CACHE_VERSION)
        digest.update(b"\0")
        digest.update(lang.encode("utf-8"))
        digest.update(b"\0")
        digest.update(text.encode("utf-8"))
        return digest.hexdigest()

    def synthesize(self, text: str, lang: str) -> bytes:
        """Return MP3 data for one segment, using the persistent cache if enabled."""
        with self._lock:
            if self._closed:
                raise PlayerClosedError("Speech synthesizer is closed")

        cache_key = self._cache_key(text, lang)
        try:
            cached = self._cache.get(cache_key)
        except (OSError, sqlite3.Error):
            logger.warning("Unable to read the speech cache", exc_info=True)
            cached = None

        if cached is not None:
            logger.debug("Speech cache hit: lang=%s chars=%d", lang, len(text))
            return cached

        logger.debug("Speech cache miss: lang=%s chars=%d", lang, len(text))
        try:
            response = self._get_session().get(
                self._build_url(text, lang),
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.RequestException as error:
            raise SynthesisError(
                f"Speech synthesis request failed for language {lang!r}"
            ) from error

        audio_data = response.content
        if not audio_data:
            raise SynthesisError("Speech provider returned an empty response")

        content_type = response.headers.get("Content-Type", "").lower()
        if content_type.startswith(("text/", "application/json")):
            raise SynthesisError(
                f"Speech provider returned unexpected content type {content_type!r}"
            )

        try:
            self._cache.set(cache_key, audio_data)
        except (OSError, sqlite3.Error):
            logger.warning("Unable to update the speech cache", exc_info=True)
        return audio_data

    def clear_cache(self) -> None:
        """Remove every cached speech item."""
        self._cache.clear()

    def close(self) -> None:
        """Close thread-local HTTP sessions and the cache."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            sessions = list(self._sessions)
            self._sessions.clear()

        for session in sessions:
            session.close()
        self._cache.close()
