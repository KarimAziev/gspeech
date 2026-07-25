#!/usr/bin/env python3

"""Unit tests."""

import itertools
import logging
import os
import socket
import sys
import tempfile
import unittest

import gspeech

gspeech.speech_segment.web_cache.DISABLE_PERSISTENT_CACHING = True
RUN_INTEGRATION_TESTS = os.environ.get("GSPEECH_RUN_INTEGRATION_TESTS") == "1"


def is_internet_reachable():
    """Return True if we can reach remote servers."""
    try:
        # open TCP socket to Google DNS server
        with socket.create_connection(("8.8.8.8", 53)):
            pass
    except OSError as e:
        if e.errno == 101:
            return False
        raise
    return True


class TestGoogleSpeech(unittest.TestCase):
    """Test case."""

    @unittest.skipUnless(
        RUN_INTEGRATION_TESTS and is_internet_reachable(),
        "Set GSPEECH_RUN_INTEGRATION_TESTS=1 to run audio integration tests",
    )
    def test_speech_lorem_ipsum(self):
        """Play some reference speeches."""
        speeches = (
            "Lorem Ipsum is simply dummy text of the printing and typesetting industry. Lorem Ipsum has been the "
            "industry's standard dummy text ever since the 1500s, when an unknown printer took a galley of type and "
            "scrambled it to make a type specimen book.",
            "Le Lorem Ipsum est simplement du faux texte employé dans la composition et la mise en page avant "
            "impression. Le Lorem Ipsum est le faux texte standard de l'imprimerie depuis les années 1500, quand un"
            "peintre anonyme assembla ensemble des morceaux de texte pour réaliser un livre spécimen de polices de "
            "texte.",
        )
        for lang, speech in zip(("en", "fr"), speeches):
            gspeech.Speech(speech, lang).play()

    def test_split_test(self):
        """Split input text."""
        text = "Aaaa, bbbb. Cccc, dddd. %s. %s, %s. %s? %s ! %s, %s %s. %s, %s %s" % (
            "e" * (gspeech.Speech.MAX_SEGMENT_SIZE + 10),
            "f" * (gspeech.Speech.MAX_SEGMENT_SIZE - 1),
            "g" * (gspeech.Speech.MAX_SEGMENT_SIZE),
            "h" * (gspeech.Speech.MAX_SEGMENT_SIZE),
            "i" * (gspeech.Speech.MAX_SEGMENT_SIZE),
            "j" * (gspeech.Speech.MAX_SEGMENT_SIZE + 1),
            "k" * gspeech.Speech.MAX_SEGMENT_SIZE,
            "l" * 5,
            "m" * (gspeech.Speech.MAX_SEGMENT_SIZE - 20),
            "n" * 10,
            "o" * 15,
        )
        split_text = (
            "Aaaa, bbbb. Cccc, dddd.",
            "%s" % ("e" * gspeech.Speech.MAX_SEGMENT_SIZE),
            "%s." % ("e" * 10),
            "%s," % ("f" * (gspeech.Speech.MAX_SEGMENT_SIZE - 1)),
            "%s" % ("g" * gspeech.Speech.MAX_SEGMENT_SIZE),
            "h" * gspeech.Speech.MAX_SEGMENT_SIZE,
            "i" * gspeech.Speech.MAX_SEGMENT_SIZE,
            "j" * gspeech.Speech.MAX_SEGMENT_SIZE,
            "j,",
            "k" * gspeech.Speech.MAX_SEGMENT_SIZE,
            "lllll. %s," % ("m" * (gspeech.Speech.MAX_SEGMENT_SIZE - 20)),
            "%s %s" % ("n" * 10, "o" * 15),
        )

        # input is text string
        speech = gspeech.Speech(text, "en")
        for segment, ref_text in itertools.zip_longest(speech, split_text):
            self.assertEqual(segment.text, ref_text)

        # input is stdin
        with tempfile.SpooledTemporaryFile(mode="w+t") as text_file:
            for i in range(3):
                text_file.write(text)
                text_file.write("\n")
            text_file.seek(0)
            original_stdin, sys.stdin = sys.stdin, text_file
            speech = gspeech.Speech("-", "fr")
            for i, (segment, ref_text) in enumerate(
                zip(speech, itertools.cycle(split_text)), 1
            ):
                self.assertEqual(segment.text, ref_text)
            self.assertEqual(i, len(split_text * 3))  # pyright: ignore
            sys.stdin = original_stdin


if __name__ == "__main__":
    # disable logging
    logging.basicConfig(level=logging.CRITICAL + 1)

    # run tests
    unittest.main()
