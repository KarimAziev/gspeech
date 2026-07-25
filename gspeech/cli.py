"""Command-line interface for :mod:`gspeech`."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence

from gspeech.config import SUPPORTED_LANGUAGES
from gspeech.player import SpeechPlayer, SpeechPolicy
from gspeech.speech import Speech
from gspeech.version import version


def build_parser() -> argparse.ArgumentParser:
    """Build and return the command-line argument parser."""
    parser = argparse.ArgumentParser(
        prog="gspeech",
        description="Synthesize speech with the Google Translate TTS API",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "speech",
        help="Text to speak, or '-' to read standard input",
    )
    parser.add_argument(
        "-l",
        "--lang",
        choices=SUPPORTED_LANGUAGES,
        default="en",
        help="Language",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Save MP3 data to this path instead of playing it",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Show lifecycle details; repeat for debug output",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {version}",
    )
    return parser


def _configure_logging(verbosity: int) -> None:
    if verbosity <= 0:
        return
    level = logging.INFO if verbosity == 1 else logging.DEBUG
    logging.basicConfig(
        level=level,
        format="%(levelname)s %(name)s: %(message)s",
    )


def _raise_if_failed(result) -> None:
    result.raise_for_error()


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command-line interface and return a process exit status."""
    args = build_parser().parse_args(argv)
    _configure_logging(args.verbose)

    try:
        if args.output:
            text = sys.stdin.read() if args.speech == "-" else args.speech
            Speech(text, args.lang).save(args.output)
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
                    _raise_if_failed(result)
                return 0

            result = player.play(args.speech, args.lang)
            _raise_if_failed(result)
            return 0
    except KeyboardInterrupt:
        return 130
    except Exception as error:
        print(f"gspeech: {error}", file=sys.stderr)
        return 1
