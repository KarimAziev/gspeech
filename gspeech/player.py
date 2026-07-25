"""Interruptible speech playback with replace-or-queue semantics."""

from __future__ import annotations

import collections
import concurrent.futures
import logging
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from gspeech.audio import AudioBackend, MiniaudioBackend
from gspeech.client import GoogleTranslateTTSClient, Synthesizer
from gspeech.exceptions import GSpeechError, PlayerClosedError
from gspeech.speech import Speech
from gspeech.speech_segment import SpeechSegment

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


_FINAL_STATUSES = frozenset(
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

    def raise_for_error(self) -> None:
        """Raise the underlying error when this result represents a failure."""
        if self.status is not SpeechStatus.FAILED:
            return
        if self.error is not None:
            raise self.error
        raise GSpeechError("Speech request failed without an underlying error")


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
            if self._status not in _FINAL_STATUSES:
                self._status = status

    def _finish(self, status: SpeechStatus, error: Exception | None = None) -> bool:
        if status not in _FINAL_STATUSES:
            raise ValueError(f"{status!r} is not a final speech status")
        with self._lock:
            if self._status in _FINAL_STATUSES:
                return False
            self._status = status
            self._error = error
            self._done.set()
            return True


@dataclass
class _SpeechRequest:
    speech: Speech
    handle: SpeechHandle
    cancel_event: threading.Event
    submitted_at: float


class SpeechPlayer:
    """
    Play speech on a dedicated worker with deterministic interruption.

    The default ``replace`` policy interrupts active speech and discards older
    pending requests. Downloads run on a bounded executor so the player worker can
    observe cancellation even while the HTTP client remains blocked.
    """

    def __init__(
        self,
        *,
        backend: AudioBackend | None = None,
        synthesizer: Synthesizer | None = None,
        buffer_size_msec: int = 100,
        download_workers: int = 2,
    ) -> None:
        if download_workers <= 0:
            raise ValueError("download_workers must be greater than zero")
        self._backend = (
            backend
            if backend is not None
            else MiniaudioBackend(buffer_size_msec=buffer_size_msec)
        )
        self._synthesizer = synthesizer or GoogleTranslateTTSClient()
        self._downloads = concurrent.futures.ThreadPoolExecutor(
            max_workers=download_workers,
            thread_name_prefix="gspeech-download",
        )
        self._condition = threading.Condition()
        self._close_lock = threading.Lock()
        self._pending: collections.deque[_SpeechRequest] = collections.deque()
        self._current: _SpeechRequest | None = None
        self._closed = False
        self._shutdown_complete = False
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
            submitted_at=time.monotonic(),
        )
        interrupted: list[_SpeechRequest] = []

        with self._condition:
            if self._closed:
                raise PlayerClosedError("SpeechPlayer is closed")

            if selected_policy is SpeechPolicy.REPLACE:
                interrupted.extend(self._pending)
                self._pending.clear()
                if self._current is not None:
                    self._current.cancel_event.set()

            self._pending.append(request)
            queue_size = len(self._pending)
            self._condition.notify()

        for old_request in interrupted:
            old_request.cancel_event.set()
            self._finish(old_request, SpeechStatus.INTERRUPTED)

        logger.info(
            "Speech request submitted: id=%s lang=%s chars=%d policy=%s queued=%d",
            request_id,
            speech.lang,
            len(speech.text),
            selected_policy.value,
            queue_size,
        )
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

    def stop(
        self,
        *,
        wait: bool = False,
        timeout: float | None = None,
    ) -> bool:
        """
        Interrupt active speech and discard pending requests.

        Return whether work was interrupted. With ``wait=True``, wait until the
        active request acknowledges cancellation.
        """
        interrupted: list[_SpeechRequest]
        active_handle: SpeechHandle | None = None
        with self._condition:
            interrupted = list(self._pending)
            self._pending.clear()
            if self._current is not None:
                self._current.cancel_event.set()
                active_handle = self._current.handle

        for request in interrupted:
            request.cancel_event.set()
            self._finish(request, SpeechStatus.INTERRUPTED)

        changed = bool(interrupted) or active_handle is not None
        if wait and active_handle is not None:
            active_handle.wait(timeout)
        return changed

    def close(self, *, timeout: float | None = None) -> None:
        """Stop requests, terminate workers, and close owned dependencies."""
        with self._close_lock:
            interrupted: list[_SpeechRequest] = []
            with self._condition:
                if not self._closed:
                    self._closed = True
                    interrupted = list(self._pending)
                    self._pending.clear()
                    if self._current is not None:
                        self._current.cancel_event.set()
                    self._condition.notify()

            for request in interrupted:
                request.cancel_event.set()
                self._finish(request, SpeechStatus.INTERRUPTED)

            if threading.current_thread() is self._worker:
                return
            if self._shutdown_complete:
                return

            self._worker.join(timeout)
            if self._worker.is_alive():
                raise TimeoutError("SpeechPlayer worker did not stop in time")
            self._downloads.shutdown(wait=True, cancel_futures=True)
            self._synthesizer.close()
            self._shutdown_complete = True

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
            self._finish(interrupted, SpeechStatus.INTERRUPTED)
            return True
        return False

    def _finish(
        self,
        request: _SpeechRequest,
        status: SpeechStatus,
        error: Exception | None = None,
    ) -> None:
        if request.handle._finish(status, error):
            logger.info(
                "Speech request finished: id=%s status=%s elapsed=%.3fs",
                request.handle.id,
                status.value,
                time.monotonic() - request.submitted_at,
            )

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
            try:
                self._backend.close()
            except Exception:
                logger.exception("Unable to close the audio backend")

    def _process(self, request: _SpeechRequest) -> None:
        try:
            status = self._play_segments(request)
        except Exception as error:
            if request.cancel_event.is_set():
                self._finish(request, SpeechStatus.INTERRUPTED)
            else:
                logger.error(
                    "Speech request failed: id=%s lang=%s chars=%d error=%s",
                    request.handle.id,
                    request.handle.lang,
                    len(request.handle.text),
                    type(error).__name__,
                )
                self._finish(request, SpeechStatus.FAILED, error)
        else:
            self._finish(request, status)

    def _play_segments(self, request: _SpeechRequest) -> SpeechStatus:
        if request.cancel_event.is_set():
            return SpeechStatus.INTERRUPTED

        segments = list(request.speech)
        if not segments:
            return SpeechStatus.COMPLETED

        request.handle._set_status(SpeechStatus.DOWNLOADING)
        current_audio = self._submit_download(segments[0])

        for index, segment in enumerate(segments):
            audio_data = self._wait_for_audio(current_audio, request.cancel_event)
            if audio_data is None:
                return SpeechStatus.INTERRUPTED

            next_audio = (
                self._submit_download(segments[index + 1])
                if index + 1 < len(segments)
                else None
            )

            request.handle._set_status(SpeechStatus.PLAYING)
            logger.debug(
                "Speech playback started: id=%s segment=%d/%d",
                request.handle.id,
                segment.segment_num + 1,
                segment.segment_count,
            )
            completed = self._backend.play(audio_data, request.cancel_event)
            if not completed or request.cancel_event.is_set():
                if next_audio is not None:
                    next_audio.cancel()
                return SpeechStatus.INTERRUPTED

            if next_audio is not None:
                request.handle._set_status(SpeechStatus.DOWNLOADING)
                current_audio = next_audio

        return SpeechStatus.COMPLETED

    def _submit_download(
        self,
        segment: SpeechSegment,
    ) -> concurrent.futures.Future[bytes]:
        return self._downloads.submit(
            self._synthesizer.synthesize,
            segment.text,
            segment.lang,
        )

    @staticmethod
    def _wait_for_audio(
        future: concurrent.futures.Future[bytes],
        cancel_event: threading.Event,
    ) -> bytes | None:
        while True:
            if cancel_event.is_set():
                future.cancel()
                return None
            try:
                return future.result(timeout=0.05)
            except concurrent.futures.TimeoutError:
                continue
