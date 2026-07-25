import io
import tempfile
import unittest
import warnings
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from gspeech import Speech, SpeechSegment, available_languages


class FakeSynthesizer:
    def __init__(self):
        self.calls = []
        self.closed = False

    def synthesize(self, text, lang):
        self.calls.append((text, lang))
        return f"<{text}>".encode()

    def close(self):
        self.closed = True


class TestSpeech(unittest.TestCase):
    def test_available_languages_returns_fresh_options(self):
        first = available_languages()
        second = available_languages()

        self.assertEqual(first, second)
        self.assertIsNot(first[0], second[0])
        first[0]["label"] = "Changed"
        self.assertNotEqual(first, available_languages())

    def test_normalizes_and_splits_text(self):
        speech = Speech("  hello\n\tworld  ", "en")
        self.assertEqual(speech.text, "hello world")
        self.assertEqual([segment.text for segment in speech], ["hello world"])

    def test_long_text_splits_at_natural_boundaries(self):
        text = "first sentence. " + ("x" * 195) + " final"
        segments = list(Speech(text, "en"))

        self.assertGreater(len(segments), 1)
        self.assertTrue(
            all(len(segment.text) <= Speech.MAX_SEGMENT_SIZE for segment in segments)
        )
        self.assertEqual(
            [segment.segment_num for segment in segments],
            list(range(len(segments))),
        )
        self.assertTrue(
            all(segment.segment_count == len(segments) for segment in segments)
        )

    def test_speech_is_iterable_but_not_an_iterator(self):
        speech = Speech("hello", "en")
        self.assertEqual(next(iter(speech)).text, "hello")
        with self.assertRaises(TypeError):
            next(cast(Any, speech))

    def test_hyphen_is_literal_library_text(self):
        self.assertEqual([segment.text for segment in Speech("-", "en")], ["-"])

    def test_invalid_language_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unsupported language"):
            Speech("hello", "not-a-language")

    def test_write_to_uses_injected_synthesizer_without_closing_it(self):
        synthesizer = FakeSynthesizer()
        output = io.BytesIO()

        Speech("hello", "en").write_to(output, synthesizer=synthesizer)

        self.assertEqual(output.getvalue(), b"<hello>")
        self.assertEqual(synthesizer.calls, [("hello", "en")])
        self.assertFalse(synthesizer.closed)

    def test_save_writes_binary_audio(self):
        synthesizer = FakeSynthesizer()
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "speech.mp3"
            Speech("hello", "en").save(path, synthesizer=synthesizer)
            self.assertEqual(path.read_bytes(), b"<hello>")

    def test_savef_is_a_deprecated_alias(self):
        output = io.BytesIO()
        with (
            warnings.catch_warnings(record=True) as captured,
            patch(
                "gspeech.speech.GoogleTranslateTTSClient",
                return_value=FakeSynthesizer(),
            ),
        ):
            warnings.simplefilter("always")
            Speech("hello", "en").savef(output)

        self.assertEqual(output.getvalue(), b"<hello>")
        self.assertTrue(any(item.category is DeprecationWarning for item in captured))

    def test_segment_is_an_immutable_value(self):
        segment = SpeechSegment("hello", "en", 0, 1)
        with self.assertRaises(FrozenInstanceError):
            cast(Any, segment).text = "changed"


if __name__ == "__main__":
    unittest.main()
