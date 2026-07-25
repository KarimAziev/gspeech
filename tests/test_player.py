import threading
import time
import unittest
from unittest.mock import patch

from gspeech import (
    Speech,
    SpeechPlayer,
    SpeechPolicy,
    SpeechStatus,
)
from gspeech.speech_segment import SpeechSegment


class ControlledBackend:
    def __init__(self, blocked_audio=()):
        self.blocked_audio = set(blocked_audio)
        self.played = []
        self.interrupted = []
        self.closed = False
        self._condition = threading.Condition()

    def play(self, audio_data, cancel_event):
        with self._condition:
            self.played.append(audio_data)
            self._condition.notify_all()

        if audio_data in self.blocked_audio:
            cancel_event.wait()
            self.interrupted.append(audio_data)
            return False
        return not cancel_event.is_set()

    def close(self):
        self.closed = True

    def wait_until_playing(self, audio_data, timeout=1.0):
        deadline = time.monotonic() + timeout
        with self._condition:
            while audio_data not in self.played:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(remaining)
        return True


class FailingBackend(ControlledBackend):
    def play(self, audio_data, cancel_event):
        raise RuntimeError("audio device failed")


def segment_audio(segment):
    return segment.text.encode()


class TestSpeechPlayer(unittest.TestCase):
    def test_speech_completes(self):
        backend = ControlledBackend()
        with patch.object(SpeechSegment, "get_audio_data", segment_audio):
            with SpeechPlayer(backend=backend) as player:
                result = player.play("hello")

        self.assertEqual(result.status, SpeechStatus.COMPLETED)
        self.assertEqual(backend.played, [b"hello"])
        self.assertTrue(backend.closed)

    def test_new_speech_interrupts_current_speech(self):
        backend = ControlledBackend(blocked_audio={b"first"})
        with patch.object(SpeechSegment, "get_audio_data", segment_audio):
            with SpeechPlayer(backend=backend) as player:
                first = player.speak("first")
                self.assertTrue(backend.wait_until_playing(b"first"))

                second = player.speak("second")

                first_result = first.wait(1)
                second_result = second.wait(1)

        self.assertEqual(first_result.status, SpeechStatus.INTERRUPTED)
        self.assertEqual(second_result.status, SpeechStatus.COMPLETED)
        self.assertEqual(backend.played, [b"first", b"second"])
        self.assertEqual(backend.interrupted, [b"first"])

    def test_replace_discards_pending_speech(self):
        backend = ControlledBackend(blocked_audio={b"first"})
        with patch.object(SpeechSegment, "get_audio_data", segment_audio):
            with SpeechPlayer(backend=backend) as player:
                first = player.speak("first")
                self.assertTrue(backend.wait_until_playing(b"first"))
                pending = player.speak("pending", policy=SpeechPolicy.ENQUEUE)

                latest = player.speak("latest")

                self.assertEqual(pending.wait(1).status, SpeechStatus.INTERRUPTED)
                self.assertEqual(first.wait(1).status, SpeechStatus.INTERRUPTED)
                self.assertEqual(latest.wait(1).status, SpeechStatus.COMPLETED)

        self.assertEqual(backend.played, [b"first", b"latest"])

    def test_stop_interrupts_active_and_pending_speech(self):
        backend = ControlledBackend(blocked_audio={b"first"})
        with patch.object(SpeechSegment, "get_audio_data", segment_audio):
            with SpeechPlayer(backend=backend) as player:
                active = player.speak("first")
                self.assertTrue(backend.wait_until_playing(b"first"))
                pending = player.speak("second", policy=SpeechPolicy.ENQUEUE)

                player.stop()

                self.assertEqual(active.wait(1).status, SpeechStatus.INTERRUPTED)
                self.assertEqual(pending.wait(1).status, SpeechStatus.INTERRUPTED)

        self.assertEqual(backend.played, [b"first"])

    def test_handle_can_cancel_its_own_request(self):
        backend = ControlledBackend(blocked_audio={b"hello"})
        with patch.object(SpeechSegment, "get_audio_data", segment_audio):
            with SpeechPlayer(backend=backend) as player:
                handle = player.speak("hello")
                self.assertTrue(backend.wait_until_playing(b"hello"))

                self.assertTrue(handle.cancel())
                self.assertEqual(handle.wait(1).status, SpeechStatus.INTERRUPTED)
                self.assertFalse(handle.cancel())

    def test_enqueue_preserves_order(self):
        backend = ControlledBackend()
        with patch.object(SpeechSegment, "get_audio_data", segment_audio):
            with SpeechPlayer(backend=backend) as player:
                first = player.speak("first", policy=SpeechPolicy.ENQUEUE)
                second = player.speak("second", policy=SpeechPolicy.ENQUEUE)

                self.assertEqual(first.wait(1).status, SpeechStatus.COMPLETED)
                self.assertEqual(second.wait(1).status, SpeechStatus.COMPLETED)

        self.assertEqual(backend.played, [b"first", b"second"])

    def test_backend_failure_is_reported_by_handle(self):
        backend = FailingBackend()
        with patch.object(SpeechSegment, "get_audio_data", segment_audio):
            with SpeechPlayer(backend=backend) as player:
                with self.assertLogs("gspeech.player", level="ERROR"):
                    result = player.play("hello")

        self.assertEqual(result.status, SpeechStatus.FAILED)
        self.assertIsInstance(result.error, RuntimeError)
        self.assertEqual(str(result.error), "audio device failed")

    def test_wait_times_out_without_cancelling_request(self):
        backend = ControlledBackend(blocked_audio={b"hello"})
        with patch.object(SpeechSegment, "get_audio_data", segment_audio):
            with SpeechPlayer(backend=backend) as player:
                handle = player.speak("hello")
                self.assertTrue(backend.wait_until_playing(b"hello"))

                with self.assertRaises(TimeoutError):
                    handle.wait(0.001)

                self.assertFalse(handle.done)
                player.stop()
                self.assertEqual(handle.wait(1).status, SpeechStatus.INTERRUPTED)

    def test_blocking_speech_api_accepts_shared_player(self):
        backend = ControlledBackend()
        with patch.object(SpeechSegment, "get_audio_data", segment_audio):
            with SpeechPlayer(backend=backend) as player:
                Speech("hello", "en").play(player)

        self.assertEqual(backend.played, [b"hello"])

    def test_closed_player_rejects_new_requests(self):
        backend = ControlledBackend()
        player = SpeechPlayer(backend=backend)
        player.close()
        player.close()

        self.assertTrue(backend.closed)
        with self.assertRaisesRegex(RuntimeError, "closed"):
            player.speak("too late")


if __name__ == "__main__":
    unittest.main()
