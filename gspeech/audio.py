"""Audio playback backends used by :mod:`gspeech`."""

from __future__ import annotations

import threading
from collections.abc import Sequence
from typing import Protocol

import miniaudio


class AudioBackend(Protocol):
    """Interface implemented by synchronous, interruptible audio backends."""

    def play(self, audio_data: bytes, cancel_event: threading.Event) -> bool:
        """
        Play encoded audio data.

        Return ``True`` when playback finishes and ``False`` when it is interrupted.
        """
        raise NotImplementedError

    def close(self) -> None:
        """Release resources owned by the backend."""


class MiniaudioBackend:
    """Play MP3 data through a reusable Miniaudio output device."""

    def __init__(
        self,
        *,
        buffer_size_msec: int = 100,
        nchannels: int = 2,
        sample_rate: int = 44_100,
        backends: Sequence[miniaudio.Backend] | None = None,
    ) -> None:
        if buffer_size_msec <= 0:
            raise ValueError("buffer_size_msec must be greater than zero")
        if nchannels not in (1, 2):
            raise ValueError("nchannels must be 1 or 2")
        if sample_rate <= 0:
            raise ValueError("sample_rate must be greater than zero")

        self.buffer_size_msec = buffer_size_msec
        self.nchannels = nchannels
        self.sample_rate = sample_rate
        self.backends = list(backends) if backends is not None else None
        self._device: miniaudio.PlaybackDevice | None = None

    def _get_device(self) -> miniaudio.PlaybackDevice:
        if self._device is None:
            self._device = miniaudio.PlaybackDevice(
                output_format=miniaudio.SampleFormat.SIGNED16,
                nchannels=self.nchannels,
                sample_rate=self.sample_rate,
                buffersize_msec=self.buffer_size_msec,
                backends=self.backends,
            )
        return self._device

    def play(self, audio_data: bytes, cancel_event: threading.Event) -> bool:
        """
        Decode and play MP3 data until completion or cancellation.

        Decoder exceptions are captured inside the audio callback and re-raised on
        the player worker instead of escaping from Miniaudio's callback thread.
        """
        if cancel_event.is_set():
            return False

        source = miniaudio.stream_memory(
            audio_data,
            output_format=miniaudio.SampleFormat.SIGNED16,
            nchannels=self.nchannels,
            sample_rate=self.sample_rate,
        )
        finished = threading.Event()
        errors: list[Exception] = []

        def cancellable_stream():
            required_frames = yield b""
            try:
                while not cancel_event.is_set():
                    try:
                        samples = source.send(required_frames)
                    except StopIteration:
                        return
                    required_frames = yield samples
            except Exception as error:
                errors.append(error)
            finally:
                try:
                    source.close()
                finally:
                    finished.set()

        stream = cancellable_stream()
        next(stream)
        device = self._get_device()

        try:
            device.start(stream)
            finished.wait()
        finally:
            device.stop()
            stream.close()

        if errors:
            raise errors[0]
        return not cancel_event.is_set()

    def close(self) -> None:
        """Stop playback and close the output device."""
        if self._device is not None:
            self._device.close()
            self._device = None
