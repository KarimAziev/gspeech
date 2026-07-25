import unittest
import warnings

from gspeech.preloader_thread import PreloaderThread
from gspeech.speech_segment import SpeechSegment


class FakeSynthesizer:
    def __init__(self):
        self.calls = []
        self.closed = False

    def synthesize(self, text, lang):
        self.calls.append((text, lang))
        if text == "bad":
            raise RuntimeError("failed")
        return b"audio"

    def close(self):
        self.closed = True


class TestPreloaderThread(unittest.TestCase):
    def test_is_deprecated_but_continues_after_segment_failure(self):
        synthesizer = FakeSynthesizer()
        segments = (
            SpeechSegment("bad", "en", 0, 2),
            SpeechSegment("good", "en", 1, 2),
        )
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            thread = PreloaderThread(
                segments,
                synthesizer=synthesizer,
                name="test-preloader",
            )

        with self.assertLogs("gspeech.preloader_thread", level="ERROR"):
            thread.start()
            thread.join(1)

        self.assertFalse(thread.is_alive())
        self.assertEqual(synthesizer.calls, [("bad", "en"), ("good", "en")])
        self.assertEqual(len(thread.errors), 1)
        self.assertFalse(synthesizer.closed)
        self.assertTrue(any(item.category is DeprecationWarning for item in captured))


if __name__ == "__main__":
    unittest.main()
