"""Opt-in integration test for the undocumented external TTS endpoint."""

import os
import unittest

from gspeech import GoogleTranslateTTSClient

RUN_INTEGRATION_TESTS = os.environ.get("GSPEECH_RUN_INTEGRATION_TESTS") == "1"


class TestGoogleTranslateIntegration(unittest.TestCase):
    @unittest.skipUnless(
        RUN_INTEGRATION_TESTS,
        "Set GSPEECH_RUN_INTEGRATION_TESTS=1 to call the external TTS endpoint",
    )
    def test_synthesizes_real_audio_without_playing_it(self):
        with GoogleTranslateTTSClient(cache_enabled=False) as client:
            audio_data = client.synthesize("gspeech integration test", "en")

        self.assertGreater(len(audio_data), 100)


if __name__ == "__main__":
    unittest.main()
