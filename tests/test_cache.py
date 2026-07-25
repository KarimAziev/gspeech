import sqlite3
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from gspeech._cache import NullAudioCache, SQLiteAudioCache


class TestNullAudioCache(unittest.TestCase):
    def test_operations_are_noops(self):
        cache = NullAudioCache()
        self.assertIsNone(cache.get("key"))
        cache.set("key", b"audio")
        cache.clear()
        cache.close()
        self.assertIsNone(cache.get("key"))


class TestSQLiteAudioCache(unittest.TestCase):
    def test_rejects_invalid_limits(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "cache.sqlite3"
            with self.assertRaises(ValueError):
                SQLiteAudioCache(path, ttl_seconds=0, max_entries=1)
            with self.assertRaises(ValueError):
                SQLiteAudioCache(path, ttl_seconds=1, max_entries=0)

    def test_get_set_clear_and_expiration(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "cache.sqlite3"
            cache = SQLiteAudioCache(path, ttl_seconds=10, max_entries=2)
            self.assertIsNone(cache.get("missing"))

            cache.set("first", b"one")
            cache.set("second", b"two")
            self.assertEqual(cache.get("first"), b"one")

            with closing(sqlite3.connect(path)) as connection, connection:
                connection.execute(
                    "UPDATE audio_cache SET created_at = ? WHERE key = ?",
                    (time.time() - 20, "first"),
                )
            self.assertIsNone(cache.get("first"))

            cache.clear()
            self.assertIsNone(cache.get("second"))
            cache.close()

    def test_prunes_least_recently_used_entries(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = SQLiteAudioCache(
                Path(temp_dir) / "cache.sqlite3",
                ttl_seconds=10,
                max_entries=2,
            )
            cache.set("first", b"one")
            cache.set("second", b"two")
            self.assertEqual(cache.get("first"), b"one")
            cache.set("third", b"three")

            self.assertEqual(cache.get("first"), b"one")
            self.assertIsNone(cache.get("second"))
            self.assertEqual(cache.get("third"), b"three")
            cache.close()

    def test_closes_each_database_connection(self):
        connections: list[sqlite3.Connection] = []
        original_connect = SQLiteAudioCache._connect

        def tracked_connect(cache: SQLiteAudioCache) -> sqlite3.Connection:
            connection = original_connect(cache)
            connections.append(connection)
            return connection

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(SQLiteAudioCache, "_connect", tracked_connect):
                cache = SQLiteAudioCache(
                    Path(temp_dir) / "cache.sqlite3",
                    ttl_seconds=10,
                    max_entries=2,
                )
                cache.set("key", b"audio")
                self.assertEqual(cache.get("key"), b"audio")
                cache.clear()

            self.assertTrue(connections)
            for connection in connections:
                with self.assertRaises(sqlite3.ProgrammingError):
                    connection.execute("SELECT 1")


if __name__ == "__main__":
    unittest.main()
