import threading
import time
import unittest

import requests

from gspeech import (
    PlayerClosedError,
    Speech,
    SpeechPlayer,
    SpeechPolicy,
    SpeechStatus,
    SynthesisError,
)


class ControlledSynthesizer:
    def __init__(self, blocked_text=(), failures=()):
        self.blocked_text = set(blocked_text)
        self.failures = set(failures)
        self.calls = []
        self.closed = False
        self._condition = threading.Condition()
        self._release = threading.Event()
        self._active = 0
        self.max_active = 0

    def synthesize(self, text, lang):
        with self._condition:
            self.calls.append((text, lang))
            self._active += 1
            self.max_active = max(self.max_active, self._active)
            self._condition.notify_all()
        try:
            if text in self.failures:
                raise RuntimeError("synthesis failed")
            if text in self.blocked_text:
                self._release.wait(2)
            return text.encode()
        finally:
            with self._condition:
                self._active -= 1
                self._condition.notify_all()

    def wait_until_called(self, text, timeout=1.0):
        deadline = time.monotonic() + timeout
        with self._condition:
            while not any(call[0] == text for call in self.calls):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(remaining)
        return True

    def release(self):
        self._release.set()

    def close(self):
        self._release.set()
        self.closed = True


class PrivacyFailureSynthesizer(ControlledSynthesizer):
    def synthesize(self, text, lang):
        try:
            raise requests.Timeout("https://provider.invalid?q=private-message")
        except requests.Timeout as error:
            raise SynthesisError("Synthesis failed") from error


class ControlledBackend:
    def __init__(self, blocked_audio=(), failures=()):
        self.blocked_audio = set(blocked_audio)
        self.failures = set(failures)
        self.played = []
        self.interrupted = []
        self.closed = False
        self._condition = threading.Condition()

    def play(self, audio_data, cancel_event):
        if audio_data in self.failures:
            raise RuntimeError("audio device failed")

        with self._condition:
            self.played.append(audio_data)
            self._condition.notify_all()

        if audio_data in self.blocked_audio:
            cancel_event.wait(2)
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


class ExternallyReleasedBackend(ControlledBackend):
    def __init__(self):
        super().__init__()
        self.release = threading.Event()

    def play(self, audio_data, cancel_event):
        with self._condition:
            self.played.append(audio_data)
            self._condition.notify_all()
        self.release.wait(2)
        return not cancel_event.is_set()


class TestSpeechPlayer(unittest.TestCase):
    def test_speech_completes_and_dependencies_close(self):
        backend = ControlledBackend()
        synthesizer = ControlledSynthesizer()

        with SpeechPlayer(backend=backend, synthesizer=synthesizer) as player:
            result = player.play("hello")

        self.assertEqual(result.status, SpeechStatus.COMPLETED)
        self.assertEqual(backend.played, [b"hello"])
        self.assertTrue(backend.closed)
        self.assertTrue(synthesizer.closed)

    def test_lifecycle_logs_are_useful_without_speech_text(self):
        backend = ControlledBackend()
        synthesizer = ControlledSynthesizer()
        with self.assertLogs("gspeech.player", level="INFO") as captured:
            with SpeechPlayer(backend=backend, synthesizer=synthesizer) as player:
                result = player.play("private greeting")

        output = "\n".join(captured.output)
        self.assertEqual(result.status, SpeechStatus.COMPLETED)
        self.assertIn("chars=16", output)
        self.assertIn("status=completed", output)
        self.assertNotIn("private greeting", output)

    def test_new_speech_interrupts_current_playback(self):
        backend = ControlledBackend(blocked_audio={b"first"})
        synthesizer = ControlledSynthesizer()
        with SpeechPlayer(backend=backend, synthesizer=synthesizer) as player:
            first = player.speak("first")
            self.assertTrue(backend.wait_until_playing(b"first"))

            second = player.speak("second")

            first_result = first.wait(1)
            second_result = second.wait(1)

        self.assertEqual(first_result.status, SpeechStatus.INTERRUPTED)
        self.assertEqual(second_result.status, SpeechStatus.COMPLETED)
        self.assertEqual(backend.played, [b"first", b"second"])

    def test_new_speech_interrupts_first_segment_download(self):
        backend = ControlledBackend()
        synthesizer = ControlledSynthesizer(blocked_text={"old"})
        with SpeechPlayer(backend=backend, synthesizer=synthesizer) as player:
            old = player.speak("old")
            self.assertTrue(synthesizer.wait_until_called("old"))
            replacement = player.speak("replacement")

            self.assertEqual(old.wait(1).status, SpeechStatus.INTERRUPTED)
            self.assertEqual(replacement.wait(1).status, SpeechStatus.COMPLETED)
            synthesizer.release()

        self.assertEqual(backend.played, [b"replacement"])

    def test_replacement_cancels_next_segment_prefetch(self):
        first_segment = "a" * Speech.MAX_SEGMENT_SIZE
        backend = ControlledBackend(blocked_audio={first_segment.encode()})
        synthesizer = ControlledSynthesizer(blocked_text={"b"})
        with SpeechPlayer(backend=backend, synthesizer=synthesizer) as player:
            old = player.speak(first_segment + "b")
            self.assertTrue(backend.wait_until_playing(first_segment.encode()))
            self.assertTrue(synthesizer.wait_until_called("b"))

            replacement = player.speak("replacement")
            self.assertEqual(old.wait(1).status, SpeechStatus.INTERRUPTED)
            self.assertEqual(replacement.wait(1).status, SpeechStatus.COMPLETED)
            synthesizer.release()

        self.assertEqual(
            backend.played,
            [first_segment.encode(), b"replacement"],
        )

    def test_download_executor_is_bounded_during_replacements(self):
        backend = ControlledBackend()
        synthesizer = ControlledSynthesizer(blocked_text={"first", "second"})
        with SpeechPlayer(
            backend=backend,
            synthesizer=synthesizer,
            download_workers=2,
        ) as player:
            first = player.speak("first")
            self.assertTrue(synthesizer.wait_until_called("first"))
            second = player.speak("second")
            self.assertTrue(synthesizer.wait_until_called("second"))
            third = player.speak("third")

            self.assertEqual(first.wait(1).status, SpeechStatus.INTERRUPTED)
            self.assertEqual(second.wait(1).status, SpeechStatus.INTERRUPTED)
            self.assertLessEqual(synthesizer.max_active, 2)
            synthesizer.release()
            self.assertEqual(third.wait(1).status, SpeechStatus.COMPLETED)

    def test_replace_discards_pending_speech(self):
        backend = ControlledBackend(blocked_audio={b"first"})
        synthesizer = ControlledSynthesizer()
        with SpeechPlayer(backend=backend, synthesizer=synthesizer) as player:
            first = player.speak("first")
            self.assertTrue(backend.wait_until_playing(b"first"))
            pending = player.speak("pending", policy=SpeechPolicy.ENQUEUE)
            latest = player.speak("latest")

            self.assertEqual(pending.wait(1).status, SpeechStatus.INTERRUPTED)
            self.assertEqual(first.wait(1).status, SpeechStatus.INTERRUPTED)
            self.assertEqual(latest.wait(1).status, SpeechStatus.COMPLETED)

        self.assertEqual(backend.played, [b"first", b"latest"])

    def test_stop_waits_for_active_and_interrupts_pending(self):
        backend = ControlledBackend(blocked_audio={b"first"})
        synthesizer = ControlledSynthesizer()
        with SpeechPlayer(backend=backend, synthesizer=synthesizer) as player:
            active = player.speak("first")
            self.assertTrue(backend.wait_until_playing(b"first"))
            pending = player.speak("second", policy=SpeechPolicy.ENQUEUE)

            self.assertTrue(player.stop(wait=True, timeout=1))
            self.assertEqual(active.wait(1).status, SpeechStatus.INTERRUPTED)
            self.assertEqual(pending.wait(1).status, SpeechStatus.INTERRUPTED)
            self.assertFalse(player.stop())

    def test_handle_can_cancel_its_request(self):
        backend = ControlledBackend(blocked_audio={b"hello"})
        synthesizer = ControlledSynthesizer()
        with SpeechPlayer(backend=backend, synthesizer=synthesizer) as player:
            handle = player.speak("hello")
            self.assertTrue(backend.wait_until_playing(b"hello"))
            self.assertTrue(handle.cancel())
            self.assertEqual(handle.wait(1).status, SpeechStatus.INTERRUPTED)
            self.assertFalse(handle.cancel())

    def test_pending_handle_can_cancel_itself(self):
        backend = ControlledBackend(blocked_audio={b"first"})
        synthesizer = ControlledSynthesizer()
        with SpeechPlayer(backend=backend, synthesizer=synthesizer) as player:
            first = player.speak("first")
            self.assertTrue(backend.wait_until_playing(b"first"))
            pending = player.speak("pending", policy=SpeechPolicy.ENQUEUE)

            self.assertTrue(pending.cancel())
            self.assertEqual(pending.wait(1).status, SpeechStatus.INTERRUPTED)
            player.stop(wait=True, timeout=1)
            self.assertEqual(first.wait(1).status, SpeechStatus.INTERRUPTED)

    def test_enqueue_preserves_order(self):
        backend = ControlledBackend()
        synthesizer = ControlledSynthesizer()
        with SpeechPlayer(backend=backend, synthesizer=synthesizer) as player:
            first = player.speak("first", policy=SpeechPolicy.ENQUEUE)
            second = player.speak("second", policy=SpeechPolicy.ENQUEUE)

            self.assertEqual(first.wait(1).status, SpeechStatus.COMPLETED)
            self.assertEqual(second.wait(1).status, SpeechStatus.COMPLETED)

        self.assertEqual(backend.played, [b"first", b"second"])

    def test_backend_failure_is_reported_and_can_be_raised(self):
        backend = ControlledBackend(failures={b"hello"})
        synthesizer = ControlledSynthesizer()
        with SpeechPlayer(backend=backend, synthesizer=synthesizer) as player:
            with self.assertLogs("gspeech.player", level="ERROR"):
                result = player.play("hello")

        self.assertEqual(result.status, SpeechStatus.FAILED)
        with self.assertRaisesRegex(RuntimeError, "audio device failed"):
            result.raise_for_error()

    def test_synthesis_failure_is_reported(self):
        backend = ControlledBackend()
        synthesizer = ControlledSynthesizer(failures={"hello"})
        with SpeechPlayer(backend=backend, synthesizer=synthesizer) as player:
            with self.assertLogs("gspeech.player", level="ERROR"):
                result = player.play("hello")

        self.assertEqual(result.status, SpeechStatus.FAILED)
        self.assertEqual(backend.played, [])

    def test_failure_log_does_not_render_exception_chain_with_text(self):
        backend = ControlledBackend()
        synthesizer = PrivacyFailureSynthesizer()
        with SpeechPlayer(backend=backend, synthesizer=synthesizer) as player:
            with self.assertLogs("gspeech.player", level="ERROR") as captured:
                result = player.play("private-message")

        self.assertEqual(result.status, SpeechStatus.FAILED)
        output = "\n".join(captured.output)
        self.assertNotIn("private-message", output)
        self.assertNotIn("provider.invalid", output)

    def test_wait_times_out_without_cancelling_request(self):
        backend = ControlledBackend(blocked_audio={b"hello"})
        synthesizer = ControlledSynthesizer()
        with SpeechPlayer(backend=backend, synthesizer=synthesizer) as player:
            handle = player.speak("hello")
            self.assertTrue(backend.wait_until_playing(b"hello"))
            with self.assertRaises(TimeoutError):
                handle.wait(0.001)
            self.assertFalse(handle.done)
            player.stop(wait=True, timeout=1)

    def test_blocking_speech_api_returns_result(self):
        backend = ControlledBackend()
        synthesizer = ControlledSynthesizer()
        with SpeechPlayer(backend=backend, synthesizer=synthesizer) as player:
            result = Speech("hello", "en").play(player)

        self.assertEqual(result.status, SpeechStatus.COMPLETED)

    def test_current_properties_track_playback(self):
        backend = ControlledBackend(blocked_audio={b"hello"})
        synthesizer = ControlledSynthesizer()
        with SpeechPlayer(backend=backend, synthesizer=synthesizer) as player:
            self.assertIsNone(player.current_handle)
            self.assertIsNone(player.current_text)
            self.assertFalse(player.is_playing)

            handle = player.speak("hello")
            self.assertTrue(backend.wait_until_playing(b"hello"))
            self.assertIs(player.current_handle, handle)
            self.assertEqual(player.current_text, "hello")
            self.assertTrue(player.is_playing)
            player.stop(wait=True, timeout=1)

    def test_close_timeout_can_be_retried(self):
        backend = ExternallyReleasedBackend()
        synthesizer = ControlledSynthesizer()
        player = SpeechPlayer(backend=backend, synthesizer=synthesizer)
        handle = player.speak("hello")
        self.assertTrue(backend.wait_until_playing(b"hello"))

        with self.assertRaisesRegex(TimeoutError, "did not stop"):
            player.close(timeout=0.001)

        backend.release.set()
        player.close(timeout=1)
        self.assertEqual(handle.wait(1).status, SpeechStatus.INTERRUPTED)
        self.assertTrue(backend.closed)
        self.assertTrue(synthesizer.closed)

    def test_empty_speech_completes_without_download_or_playback(self):
        backend = ControlledBackend()
        synthesizer = ControlledSynthesizer()
        with SpeechPlayer(backend=backend, synthesizer=synthesizer) as player:
            result = player.play("  ")

        self.assertEqual(result.status, SpeechStatus.COMPLETED)
        self.assertEqual(synthesizer.calls, [])
        self.assertEqual(backend.played, [])

    def test_closed_player_rejects_new_requests(self):
        backend = ControlledBackend()
        synthesizer = ControlledSynthesizer()
        player = SpeechPlayer(backend=backend, synthesizer=synthesizer)
        player.close()
        player.close()

        with self.assertRaisesRegex(PlayerClosedError, "closed"):
            player.speak("too late")


if __name__ == "__main__":
    unittest.main()
