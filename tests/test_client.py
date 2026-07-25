import sqlite3
import tempfile
import threading
import unittest
import urllib.parse
from collections.abc import Iterable
from contextlib import closing
from pathlib import Path
from typing import Any

import requests

from gspeech import GoogleTranslateTTSClient, PlayerClosedError, SynthesisError


class MemoryCache:
    def __init__(self):
        self.items = {}
        self.keys = []
        self.closed = False

    def get(self, key):
        self.keys.append(key)
        return self.items.get(key)

    def set(self, key, audio_data):
        self.keys.append(key)
        self.items[key] = audio_data

    def clear(self):
        self.items.clear()

    def close(self):
        self.closed = True


class FakeResponse:
    def __init__(
        self,
        content: bytes = b"mp3",
        content_type: str = "audio/mpeg",
        error: Exception | None = None,
    ) -> None:
        self.content = content
        self.headers = {"Content-Type": content_type}
        self.error = error

    def raise_for_status(self) -> None:
        if self.error is not None:
            raise self.error


class FakeSession:
    def __init__(
        self,
        responses: Iterable[FakeResponse | Exception] = (),
    ) -> None:
        self.responses = list(responses)
        self.requests: list[tuple[str, dict[str, Any]]] = []
        self.closed = False

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.requests.append((url, kwargs))
        if not self.responses:
            return FakeResponse()
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def close(self) -> None:
        self.closed = True


class TestGoogleTranslateTTSClient(unittest.TestCase):
    def test_rejects_invalid_timeout(self):
        with self.assertRaises(ValueError):
            GoogleTranslateTTSClient(timeout=(0, 1))
        with self.assertRaises(ValueError):
            GoogleTranslateTTSClient(timeout=(1, -1))

    def test_context_manager_and_disabled_cache(self):
        session = FakeSession()
        with GoogleTranslateTTSClient(
            cache_enabled=False,
            session_factory=lambda: session,
        ) as client:
            self.assertEqual(client.synthesize("hello", "en"), b"mp3")

        self.assertTrue(session.closed)

    def test_preserves_case_and_uses_separate_timeouts(self):
        session = FakeSession()
        client = GoogleTranslateTTSClient(
            cache=MemoryCache(),
            timeout=(1.5, 4.0),
            session_factory=lambda: session,
        )
        try:
            self.assertEqual(client.synthesize("Turn on GPS", "en"), b"mp3")
        finally:
            client.close()

        url, kwargs = session.requests[0]
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        self.assertEqual(query["q"], ["Turn on GPS"])
        self.assertEqual(kwargs["timeout"], (1.5, 4.0))
        self.assertTrue(session.closed)

    def test_cache_key_does_not_contain_text_and_cache_hit_skips_http(self):
        cache = MemoryCache()
        session = FakeSession()
        client = GoogleTranslateTTSClient(
            cache=cache,
            session_factory=lambda: session,
        )
        try:
            self.assertEqual(client.synthesize("private message", "en"), b"mp3")
            self.assertEqual(client.synthesize("private message", "en"), b"mp3")
        finally:
            client.close()

        self.assertEqual(len(session.requests), 1)
        self.assertTrue(cache.keys)
        self.assertTrue(all(len(key) == 64 for key in cache.keys))
        self.assertTrue(all("private" not in key for key in cache.keys))

    def test_persistent_database_contains_only_opaque_key(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            session = FakeSession()
            client = GoogleTranslateTTSClient(
                cache_dir=temp_dir,
                session_factory=lambda: session,
            )
            client.synthesize("very secret phrase", "en")
            client.close()

            database = Path(temp_dir) / "audio-cache.sqlite3"
            with closing(sqlite3.connect(database)) as connection, connection:
                key, audio = connection.execute(
                    "SELECT key, audio FROM audio_cache"
                ).fetchone()

        self.assertEqual(len(key), 64)
        self.assertNotIn("secret", key)
        self.assertEqual(audio, b"mp3")

    def test_empty_or_non_audio_response_is_rejected(self):
        for response in (
            FakeResponse(content=b""),
            FakeResponse(content=b"<html>", content_type="text/html"),
        ):
            with self.subTest(response=response):
                client = GoogleTranslateTTSClient(
                    cache=MemoryCache(),
                    session_factory=lambda response=response: FakeSession([response]),
                )
                try:
                    with self.assertRaises(SynthesisError):
                        client.synthesize("hello", "en")
                finally:
                    client.close()

    def test_request_error_is_wrapped_without_spoken_text(self):
        session = FakeSession([requests.Timeout("too slow")])
        client = GoogleTranslateTTSClient(
            cache=MemoryCache(),
            session_factory=lambda: session,
        )
        try:
            with self.assertRaises(SynthesisError) as raised:
                client.synthesize("my private address", "en")
        finally:
            client.close()

        self.assertNotIn("private", str(raised.exception))
        self.assertIsInstance(raised.exception.__cause__, requests.Timeout)

    def test_debug_logs_do_not_contain_text_or_url(self):
        client = GoogleTranslateTTSClient(
            cache=MemoryCache(),
            session_factory=FakeSession,
        )
        try:
            with self.assertLogs("gspeech.client", level="DEBUG") as captured:
                client.synthesize("do not log me", "en")
        finally:
            client.close()

        output = "\n".join(captured.output)
        self.assertNotIn("do not log me", output)
        self.assertNotIn("translate_tts", output)
        self.assertIn("chars=13", output)

    def test_each_download_thread_gets_its_own_session(self):
        sessions = []
        lock = threading.Lock()

        def factory():
            session = FakeSession()
            with lock:
                sessions.append(session)
            return session

        client = GoogleTranslateTTSClient(
            cache=MemoryCache(),
            session_factory=factory,
        )
        threads = [
            threading.Thread(target=client.synthesize, args=(f"text {index}", "en"))
            for index in range(2)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        client.close()

        self.assertEqual(len(sessions), 2)
        self.assertTrue(all(session.closed for session in sessions))

    def test_clear_cache_and_close_are_idempotent(self):
        cache = MemoryCache()
        cache.items["key"] = b"value"
        client = GoogleTranslateTTSClient(cache=cache)
        client.clear_cache()
        client.close()
        client.close()

        self.assertEqual(cache.items, {})
        self.assertTrue(cache.closed)
        with self.assertRaises(PlayerClosedError):
            client.synthesize("hello", "en")


if __name__ == "__main__":
    unittest.main()
