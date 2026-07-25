"""
PreloaderThread Class for Pre-loading Speech Segment Audio

This module defines the `PreloaderThread` class, which is a specialized thread used to concurrently pre-load
audio data of speech segments from the Google Translate TTS API into a cache for faster and seamless playback.

"""

import logging
import threading
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from gspeech.speech_segment import SpeechSegment


logger = logging.getLogger(__name__)


class PreloaderThread(threading.Thread):
    """Thread to pre load (download and store in cache) audio data of a segment."""

    def __init__(self, segments: List["SpeechSegment"] = [], *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.segments = segments

    def run(self) -> None:
        """
        Executes the thread's functionality to pre-load audio data for speech segments.

        The `run` method is the entry point for the thread when it is started. It iterates
        over the list of `SpeechSegment` objects (`self.segments`) and downloads and stores
        the audio data in cache if it is not already loaded. This preloading ensures faster
        playback by avoiding on-demand downloads during real-time playback.

        Workflow:
            1. For each segment in `self.segments`, it attempts to acquire the `preload_mutex`
               lock associated with the segment. This ensures that no two threads preload
               the same segment simultaneously.
            2. If the lock is successfully acquired, it checks whether the segment's audio
               data is already present in the cache using the `is_in_cache` method of
               `SpeechSegment`.
            3. If the segment is not in the cache, the `pre_load` method of `SpeechSegment`
               is invoked to download the audio data and store it in the cache.
            4. Finally, the lock is released to allow other threads to access the segment.

        Exception Handling:
            - If any exception occurs during the execution (e.g., network errors,
              unexpected issues), it is logged using the `logging` module to ensure the
              application continues to operate without disruption.

        Attributes:
            - self.segments (List[SpeechSegment]): A list of `SpeechSegment` objects for
              which the audio data should be preloaded.

        Raises:
            - Any exceptions encountered during execution are logged, but not re-raised,
              to allow other segments to be processed uninterrupted.

        Example Usage:
            ```python
            # Create and start a preloader thread
            preloader_thread = PreloaderThread(segments=speech_segments)
            preloader_thread.start()

            # Wait for the thread to complete
            preloader_thread.join()
            ```

        Logging:
            - Logs errors encountered during preloading with the segment details for
              debugging and tracing issues.
        """
        try:
            for segment in self.segments:
                acquired = segment.preload_mutex.acquire(blocking=False)
                if acquired:
                    try:
                        if not segment.is_in_cache():
                            segment.pre_load()
                    finally:
                        segment.preload_mutex.release()
        except Exception as e:
            logger.error("%s: %s" % (e.__class__.__qualname__, e))
