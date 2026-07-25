"""Command-line interface for :mod:`gspeech`."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from gspeech.config import SUPPORTED_LANGUAGES
from gspeech.player import SpeechPlayer, SpeechPolicy, SpeechStatus
from gspeech.speech import Speech


def build_parser() -> argparse.ArgumentParser:
    """Build and return the command-line argument parser."""
    parser = argparse.ArgumentParser(
        prog="gspeech",
        description="Synthesize speech with the Google Translate TTS API",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "speech",
        help="Text to speak, or '-' to read lines from standard input",
    )
    parser.add_argument(
        "-l",
        "--lang",
        choices=SUPPORTED_LANGUAGES,
        default="en",
        dest="lang",
        help="Language",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        dest="output",
        help="Save MP3 data to this path instead of playing it",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command-line interface and return a process exit status."""
    args = build_parser().parse_args(argv)
    speech = Speech(args.speech, args.lang)

    try:
        if args.output:
            speech.save(args.output)
            return 0

        with SpeechPlayer() as player:
            if args.speech == "-":
                for line in sys.stdin:
                    text = line.strip()
                    if not text:
                        continue
                    result = player.play(
                        text,
                        args.lang,
                        policy=SpeechPolicy.ENQUEUE,
                    )
                    if result.status is SpeechStatus.FAILED:
                        if result.error is not None:
                            raise result.error
                        return 1
                return 0

            result = player.play(speech)
            if result.status is SpeechStatus.FAILED:
                if result.error is not None:
                    raise result.error
                return 1
            return 0
    except KeyboardInterrupt:
        return 130
    except Exception as error:
        print(f"gspeech: {error}", file=sys.stderr)
        return 1
