import io
import threading
import unittest
import wave
from unittest.mock import patch

import miniaudio

from gspeech.audio import MiniaudioBackend
from gspeech.exceptions import PlaybackError


def silent_wav(duration_seconds=0.02, sample_rate=8_000):
    output = io.BytesIO()
    frame_count = round(duration_seconds * sample_rate)
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"\x00\x00" * frame_count)
    return output.getvalue()


class TestMiniaudioBackend(unittest.TestCase):
    def test_rejects_invalid_configuration(self):
        with self.assertRaises(ValueError):
            MiniaudioBackend(buffer_size_msec=0)
        with self.assertRaises(ValueError):
            MiniaudioBackend(nchannels=3)
        with self.assertRaises(ValueError):
            MiniaudioBackend(sample_rate=0)

    def test_wraps_decoder_initialization_errors(self):
        backend = MiniaudioBackend()
        with patch(
            "gspeech.audio.miniaudio.stream_memory",
            side_effect=RuntimeError("invalid audio"),
        ):
            with self.assertRaises(PlaybackError) as raised:
                backend.play(b"not audio", threading.Event())

        self.assertIsInstance(raised.exception.__cause__, RuntimeError)

    def test_wraps_output_device_errors(self):
        backend = MiniaudioBackend()
        with patch.object(
            backend,
            "_get_device",
            side_effect=RuntimeError("device unavailable"),
        ):
            with self.assertRaises(PlaybackError) as raised:
                backend.play(silent_wav(), threading.Event())

        self.assertIsInstance(raised.exception.__cause__, RuntimeError)

    def test_plays_encoded_memory_through_null_device(self):
        backend = MiniaudioBackend(
            buffer_size_msec=10,
            nchannels=1,
            sample_rate=8_000,
            backends=[miniaudio.Backend.NULL],
        )
        try:
            first_completed = backend.play(silent_wav(), threading.Event())
            second_completed = backend.play(silent_wav(), threading.Event())
        finally:
            backend.close()

        self.assertTrue(first_completed)
        self.assertTrue(second_completed)

    def test_interrupts_real_null_device_playback(self):
        backend = MiniaudioBackend(
            buffer_size_msec=10,
            nchannels=1,
            sample_rate=8_000,
            backends=[miniaudio.Backend.NULL],
        )
        cancelled = threading.Event()
        timer = threading.Timer(0.02, cancelled.set)
        timer.start()
        try:
            completed = backend.play(
                silent_wav(duration_seconds=2),
                cancelled,
            )
        finally:
            timer.cancel()
            backend.close()

        self.assertFalse(completed)

    def test_pre_cancelled_playback_does_not_open_device(self):
        backend = MiniaudioBackend(backends=[miniaudio.Backend.NULL])
        cancelled = threading.Event()
        cancelled.set()

        self.assertFalse(backend.play(b"not audio", cancelled))
        self.assertIsNone(backend._device)


if __name__ == "__main__":
    unittest.main()
