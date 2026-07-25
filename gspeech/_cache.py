"""Small, privacy-preserving audio caches used internally by gspeech."""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Protocol


class AudioCache(Protocol):
    """Storage interface used by the speech synthesizer."""

    def get(self, key: str) -> bytes | None:
        """Return cached audio, or ``None`` when the key is absent or expired."""
        ...

    def set(self, key: str, audio_data: bytes) -> None:
        """Store encoded audio under an opaque key."""
        ...

    def clear(self) -> None:
        """Remove every cached item."""
        ...

    def close(self) -> None:
        """Release resources owned by the cache."""
        ...


class NullAudioCache:
    """No-op cache used when persistence is disabled or unavailable."""

    def get(self, key: str) -> None:
        """Always report a cache miss."""
        return None

    def set(self, key: str, audio_data: bytes) -> None:
        """Discard audio data."""

    def clear(self) -> None:
        """Do nothing."""

    def close(self) -> None:
        """Do nothing."""


class SQLiteAudioCache:
    """Thread-safe SQLite cache whose keys contain no original speech text."""

    def __init__(
        self,
        path: Path,
        *,
        ttl_seconds: float,
        max_entries: int,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be greater than zero")
        if max_entries <= 0:
            raise ValueError("max_entries must be greater than zero")

        self.path = path
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS audio_cache (
                    key TEXT PRIMARY KEY,
                    audio BLOB NOT NULL,
                    created_at REAL NOT NULL,
                    accessed_at REAL NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=5)

    def get(self, key: str) -> bytes | None:
        now = time.time()
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT audio, created_at FROM audio_cache WHERE key = ?",
                (key,),
            ).fetchone()
            if row is None:
                return None

            audio_data, created_at = row
            if now - float(created_at) > self.ttl_seconds:
                connection.execute("DELETE FROM audio_cache WHERE key = ?", (key,))
                return None

            connection.execute(
                "UPDATE audio_cache SET accessed_at = ? WHERE key = ?",
                (now, key),
            )
            return bytes(audio_data)

    def set(self, key: str, audio_data: bytes) -> None:
        now = time.time()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO audio_cache (key, audio, created_at, accessed_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    audio = excluded.audio,
                    created_at = excluded.created_at,
                    accessed_at = excluded.accessed_at
                """,
                (key, audio_data, now, now),
            )
            connection.execute(
                """
                DELETE FROM audio_cache
                WHERE key IN (
                    SELECT key
                    FROM audio_cache
                    ORDER BY accessed_at DESC
                    LIMIT -1 OFFSET ?
                )
                """,
                (self.max_entries,),
            )

    def clear(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM audio_cache")

    def close(self) -> None:
        """Connections are short-lived, so there is nothing to release."""
