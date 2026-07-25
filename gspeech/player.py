"""Interruptible speech playback with replace-or-queue semantics."""

from __future__ import annotations

import collections
import concurrent.futures
import logging
import threading
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Callable

from gspeech.audio import AudioBackend, MiniaudioBackend
from gspeech.speech import Speech

logger = logging.getLogger(__name__)


class SpeechStatus(str, Enum):
    """Lifecycle states reported by a :class:`SpeechHandle`."""

    PENDING = "pending"
    DOWNLOADING = "downloading"
    PLAYING = "playing"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    FAILED = "failed"


class SpeechPolicy(str, Enum):
    """How a new request interacts with existing speech requests."""

    REPLACE = "replace"
    ENQUEUE = "enqueue"


FINAL_STATUSES = frozenset(
    {
        SpeechStatus.COMPLETED,
        SpeechStatus.INTERRUPTED,
        SpeechStatus.FAILED,
    }
)


@dataclass(frozen=True)
class SpeechResult:
    """Final outcome returned by :meth:`SpeechHandle.wait`."""

    request_id: str
    text: str
    lang: str
    status: SpeechStatus
    error: Exception | None = None


class SpeechHandle:
    """A thread-safe handle for observing or cancelling a speech request."""

    def __init__(
        self,
        *,
        request_id: str,
        text: str,
        lang: str,
        cancel_callback: Callable[[str], bool],
    ) -> None:
        self.id = request_id
        self.text = text
        self.lang = lang
        self._cancel_callback = cancel_callback
        self._status = SpeechStatus.PENDING
        self._error: Exception | None = None
        self._lock = threading.Lock()
        self._done = threading.Event()

    @property
    def status(self) -> SpeechStatus:
        """Return the request's current lifecycle state."""
        with self._lock:
            return self._status

    @property
    def done(self) -> bool:
        """Return whether the request has reached a final state."""
        return self._done.is_set()

    def cancel(self) -> bool:
        """Interrupt this request if it is pending or active."""
        return self._cancel_callback(self.id)

    def wait(self, timeout: float | None = None) -> SpeechResult:
        """Wait for a final result, raising :class:`TimeoutError` on timeout."""
        if not self._done.wait(timeout):
            raise TimeoutError(f"Speech request {self.id} did not finish in time")
        with self._lock:
            return SpeechResult(
                request_id=self.id,
                text=self.text,
                lang=self.lang,
                status=self._status,
                error=self._error,
            )

    def _set_status(self, status: SpeechStatus) -> None:
        with self._lock:
            if self._status not in FINAL_STATUSES:
                self._status = status

    def _finish(self, status: SpeechStatus, error: Exception | None = None) -> None:
        if status not in FINAL_STATUSES:
            raise ValueError(f"{status!r} is not a final speech status")
        with self._lock:
            if self._status in FINAL_STATUSES:
                return
            self._status = status
            self._error = error
            self._done.set()


@dataclass
class _SpeechRequest:
    speech: Speech
    handle: SpeechHandle
    cancel_event: threading.Event


class SpeechPlayer:
    """
    Play speech on a dedicated worker with deterministic interruption.

    The default ``replace`` policy interrupts active speech and discards older
    pending requests. Use ``enqueue`` when every submitted request must be heard.
    """

    def __init__(
        self,
        *,
        backend: AudioBackend | None = None,
        buffer_size_msec: int = 100,
    ) -> None:
        self._backend = (
            backend
            if backend is not None
            else MiniaudioBackend(buffer_size_msec=buffer_size_msec)
        )
        self._condition = threading.Condition()
        self._pending: collections.deque[_SpeechRequest] = collections.deque()
        self._current: _SpeechRequest | None = None
        self._closed = False
        self._worker = threading.Thread(
            target=self._run,
            name="gspeech-player",
            daemon=True,
        )
        self._worker.start()

    def __enter__(self) -> SpeechPlayer:
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    @property
    def is_playing(self) -> bool:
        """Return whether an active request is currently producing audio."""
        with self._condition:
            return (
                self._current is not None
                and self._current.handle.status is SpeechStatus.PLAYING
            )

    @property
    def current_handle(self) -> SpeechHandle | None:
        """Return the current request handle, if a request is active."""
        with self._condition:
            return self._current.handle if self._current is not None else None

    @property
    def current_text(self) -> str | None:
        """Return the current request text, if a request is active."""
        handle = self.current_handle
        return handle.text if handle is not None else None

    def speak(
        self,
        text: str | Speech,
        lang: str = "en",
        *,
        policy: SpeechPolicy | str = SpeechPolicy.REPLACE,
    ) -> SpeechHandle:
        """Submit speech and return immediately with a cancellable handle."""
        selected_policy = SpeechPolicy(policy)
        speech = text if isinstance(text, Speech) else Speech(text, lang)
        request_id = uuid.uuid4().hex
        handle = SpeechHandle(
            request_id=request_id,
            text=speech.text,
            lang=speech.lang,
            cancel_callback=self._cancel_request,
        )
        request = _SpeechRequest(
            speech=speech,
            handle=handle,
            cancel_event=threading.Event(),
        )
        interrupted: list[_SpeechRequest] = []

        with self._condition:
            if self._closed:
                raise RuntimeError("SpeechPlayer is closed")

            if selected_policy is SpeechPolicy.REPLACE:
                interrupted.extend(self._pending)
                self._pending.clear()
                if self._current is not None:
                    self._current.cancel_event.set()

            self._pending.append(request)
            self._condition.notify()

        for old_request in interrupted:
            old_request.cancel_event.set()
            old_request.handle._finish(SpeechStatus.INTERRUPTED)

        return handle

    def play(
        self,
        text: str | Speech,
        lang: str = "en",
        *,
        policy: SpeechPolicy | str = SpeechPolicy.REPLACE,
        timeout: float | None = None,
    ) -> SpeechResult:
        """Submit speech and block until it reaches a final state."""
        return self.speak(text, lang, policy=policy).wait(timeout)

    def stop(self) -> None:
        """Interrupt active speech and discard all pending requests."""
        interrupted: list[_SpeechRequest]
        with self._condition:
            interrupted = list(self._pending)
            self._pending.clear()
            if self._current is not None:
                self._current.cancel_event.set()

        for request in interrupted:
            request.cancel_event.set()
            request.handle._finish(SpeechStatus.INTERRUPTED)

    def close(self) -> None:
        """Stop playback, terminate the worker, and close the audio backend."""
        interrupted: list[_SpeechRequest]
        with self._condition:
            if self._closed:
                return
            self._closed = True
            interrupted = list(self._pending)
            self._pending.clear()
            if self._current is not None:
                self._current.cancel_event.set()
            self._condition.notify()

        for request in interrupted:
            request.cancel_event.set()
            request.handle._finish(SpeechStatus.INTERRUPTED)

        if threading.current_thread() is not self._worker:
            self._worker.join()

    def _cancel_request(self, request_id: str) -> bool:
        interrupted: _SpeechRequest | None = None
        with self._condition:
            if (
                self._current is not None
                and self._current.handle.id == request_id
                and not self._current.handle.done
            ):
                self._current.cancel_event.set()
                return True

            for request in self._pending:
                if request.handle.id == request_id:
                    self._pending.remove(request)
                    interrupted = request
                    break

        if interrupted is not None:
            interrupted.cancel_event.set()
            interrupted.handle._finish(SpeechStatus.INTERRUPTED)
            return True
        return False

    def _run(self) -> None:
        try:
            while True:
                with self._condition:
                    self._condition.wait_for(
                        lambda: self._closed or bool(self._pending)
                    )
                    if self._closed and not self._pending:
                        return
                    request = self._pending.popleft()
                    self._current = request

                self._process(request)

                with self._condition:
                    if self._current is request:
                        self._current = None
                    self._condition.notify_all()
        finally:
            self._backend.close()

    def _process(self, request: _SpeechRequest) -> None:
        try:
            status = self._play_segments(request)
        except Exception as error:
            if request.cancel_event.is_set():
                request.handle._finish(SpeechStatus.INTERRUPTED)
            else:
                logger.exception("Speech request %s failed", request.handle.id)
                request.handle._finish(SpeechStatus.FAILED, error)
        else:
            request.handle._finish(status)

    def _play_segments(self, request: _SpeechRequest) -> SpeechStatus:
        if request.cancel_event.is_set():
            return SpeechStatus.INTERRUPTED

        segments = list(request.speech)
        if not segments:
            return SpeechStatus.COMPLETED

        executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="gspeech-download",
        )
        next_audio: concurrent.futures.Future[bytes] | None = None

        try:
            request.handle._set_status(SpeechStatus.DOWNLOADING)
            audio_data = segments[0].get_audio_data()

            for index, _ in enumerate(segments):
                if request.cancel_event.is_set():
                    return SpeechStatus.INTERRUPTED

                if index + 1 < len(segments):
                    next_audio = executor.submit(segments[index + 1].get_audio_data)
                else:
                    next_audio = None

                request.handle._set_status(SpeechStatus.PLAYING)
                completed = self._backend.play(audio_data, request.cancel_event)
                if not completed or request.cancel_event.is_set():
                    return SpeechStatus.INTERRUPTED

                if next_audio is not None:
                    request.handle._set_status(SpeechStatus.DOWNLOADING)
                    audio_data = self._wait_for_audio(next_audio, request.cancel_event)
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        return SpeechStatus.COMPLETED

    @staticmethod
    def _wait_for_audio(
        future: concurrent.futures.Future[bytes],
        cancel_event: threading.Event,
    ) -> bytes:
        while True:
            if cancel_event.is_set():
                future.cancel()
                return b""
            try:
                return future.result(timeout=0.05)
            except concurrent.futures.TimeoutError:
                continue
