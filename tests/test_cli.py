import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from gspeech.cli import main
from gspeech.speech import Speech


class TestCli(unittest.TestCase):
    def test_output_mode_saves_without_opening_audio_player(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = str(Path(temp_dir) / "speech.mp3")
            with (
                patch.object(Speech, "save") as save,
                patch(
                    "gspeech.cli.SpeechPlayer",
                    side_effect=AssertionError("audio player was opened"),
                ),
            ):
                status = main(["--output", output, "hello"])

        self.assertEqual(status, 0)
        save.assert_called_once_with(output)

    def test_invalid_language_returns_argparse_error(self):
        with (
            redirect_stderr(StringIO()),
            self.assertRaises(SystemExit) as raised,
        ):
            main(["--lang", "not-a-language", "hello"])
        self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
