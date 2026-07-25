"""Exceptions raised by :mod:`gspeech`."""


class GSpeechError(Exception):
    """Base class for errors raised by gspeech."""


class SynthesisError(GSpeechError):
    """Speech audio could not be synthesized."""


class PlaybackError(GSpeechError):
    """Synthesized audio could not be played."""


class PlayerClosedError(GSpeechError):
    """A request was submitted to a closed speech player."""
