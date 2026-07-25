import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import Mock, patch

from gspeech import SpeechStatus
from gspeech.cli import main
from gspeech.player import SpeechResult


def result(status=SpeechStatus.COMPLETED, error=None):
    return SpeechResult(
        request_id="request",
        text="hello",
        lang="en",
        status=status,
        error=error,
    )


class FakePlayer:
    instance = None

    def __init__(self):
        self.calls = []
        self.results = []
        FakePlayer.instance = self

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return None

    def play(self, text, lang="en", **kwargs):
        self.calls.append((text, lang, kwargs))
        return self.results.pop(0) if self.results else result()


class TestCli(unittest.TestCase):
    def test_output_mode_saves_without_opening_player(self):
        with (
            patch("gspeech.cli.Speech") as speech_class,
            patch(
                "gspeech.cli.SpeechPlayer",
                side_effect=AssertionError("audio player was opened"),
            ),
        ):
            status = main(["--output", "speech.mp3", "hello"])

        self.assertEqual(status, 0)
        speech_class.assert_called_once_with("hello", "en")
        speech_class.return_value.save.assert_called_once_with("speech.mp3")

    def test_output_mode_reads_standard_input(self):
        with (
            patch("sys.stdin", io.StringIO("First\nSecond\n")),
            patch("gspeech.cli.Speech") as speech_class,
        ):
            status = main(["--output", "speech.mp3", "-"])

        self.assertEqual(status, 0)
        speech_class.assert_called_once_with("First\nSecond\n", "en")
        speech_class.return_value.save.assert_called_once_with("speech.mp3")

    def test_standard_input_plays_each_nonempty_line(self):
        with (
            patch("sys.stdin", io.StringIO("First\n\nSecond\n")),
            patch("gspeech.cli.SpeechPlayer", FakePlayer),
        ):
            status = main(["--lang", "fr", "-"])

        self.assertEqual(status, 0)
        self.assertIsNotNone(FakePlayer.instance)
        player = FakePlayer.instance
        assert player is not None
        self.assertEqual(
            [call[:2] for call in player.calls],
            [("First", "fr"), ("Second", "fr")],
        )

    def test_playback_failure_prints_concise_error(self):
        player = FakePlayer()
        player.results = [
            result(SpeechStatus.FAILED, RuntimeError("audio unavailable"))
        ]
        stderr = io.StringIO()
        with (
            patch("gspeech.cli.SpeechPlayer", return_value=player),
            redirect_stderr(stderr),
        ):
            status = main(["hello"])

        self.assertEqual(status, 1)
        self.assertEqual(stderr.getvalue(), "gspeech: audio unavailable\n")

    def test_keyboard_interrupt_returns_shell_status(self):
        player = Mock()
        player.__enter__ = Mock(side_effect=KeyboardInterrupt)
        player.__exit__ = Mock(return_value=None)
        with patch("gspeech.cli.SpeechPlayer", return_value=player):
            self.assertEqual(main(["hello"]), 130)

    def test_verbose_mode_configures_cli_logging(self):
        with (
            patch("gspeech.cli.logging.basicConfig") as basic_config,
            patch("gspeech.cli.SpeechPlayer", FakePlayer),
        ):
            status = main(["-vv", "hello"])

        self.assertEqual(status, 0)
        basic_config.assert_called_once()
        self.assertEqual(basic_config.call_args.kwargs["level"], 10)

    def test_default_mode_does_not_configure_host_logging(self):
        with (
            patch("gspeech.cli.logging.basicConfig") as basic_config,
            patch("gspeech.cli.SpeechPlayer", FakePlayer),
        ):
            status = main(["hello"])

        self.assertEqual(status, 0)
        basic_config.assert_not_called()

    def test_invalid_language_returns_argparse_error(self):
        with (
            redirect_stderr(io.StringIO()),
            self.assertRaises(SystemExit) as raised,
        ):
            main(["--lang", "not-a-language", "hello"])
        self.assertEqual(raised.exception.code, 2)

    def test_version_option(self):
        stdout = io.StringIO()
        with (
            redirect_stdout(stdout),
            self.assertRaises(SystemExit) as raised,
        ):
            main(["--version"])

        self.assertEqual(raised.exception.code, 0)
        self.assertRegex(stdout.getvalue(), r"^gspeech \S+")


if __name__ == "__main__":
    unittest.main()
