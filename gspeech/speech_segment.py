import collections
import logging
import os
import threading
import urllib.parse
from typing import Optional

import appdirs
import requests
import web_cache

from gspeech.audio import MiniaudioBackend

logger = logging.getLogger(__name__)


class SpeechSegment:
    """
    Text segment to be read.
    """

    BASE_URL = "https://translate.google.com/translate_tts"
    session = requests.Session()
    cache: "web_cache.WebCache"

    def __init__(
        self,
        text: str,
        lang: str,
        segment_num: int,
        segment_count: Optional[int] = None,
    ):
        """
        Initialize a SpeechSegment instance.

        Args:
            text: The text for the speech segment.
            lang: The language code for the TTS engine.
            segment_num: The segment's position in a sequence.
            segment_count: The total number of segments in the sequence (optional).
        """
        self.text = text
        self.lang = lang
        self.segment_num = segment_num
        self.segment_count = segment_count
        self.preload_mutex = threading.Lock()

        # Initialize the cache only once for the class
        if not hasattr(__class__, "cache"):
            db_filepath = os.path.join(
                appdirs.user_cache_dir(appname="gspeech", appauthor=False),
                "gspeech-cache.sqlite",
            )
            os.makedirs(os.path.dirname(db_filepath), exist_ok=True)
            cache_name = "sound_data"
            __class__.cache = web_cache.ThreadedWebCache(
                db_filepath,
                cache_name,
                expiration=60 * 60 * 24 * 365,  # 1 year
                caching_strategy=web_cache.CachingStrategy.LRU,
            )  # type: ignore
            logger.debug(
                "Total size of file '%s': %s"
                % (db_filepath, __class__.cache.getDatabaseFileSize())
            )
            purged_count = __class__.cache.purge()
            logger.debug(
                "%u obsolete entries have been removed from cache '%s'"
                % (purged_count, cache_name)
            )
            row_count = len(__class__.cache)
            logger.debug("Cache '%s' contains %u entries" % (cache_name, row_count))

    def __str__(self) -> str:
        """
        Return the text of the speech segment.
        """
        return self.text

    def is_in_cache(self) -> bool:
        """
        Check if the audio data for this segment is already cached.

        Returns:
            True if the audio data is in cache, otherwise False.
        """
        url = self.build_url()
        return url in __class__.cache

    def pre_load(self) -> None:
        """
        Preload audio data for the segment by storing it in the cache for quicker playback.
        """
        logger.debug("Preloading segment '%s'" % (self))
        real_url = self.build_url()
        cache_url = self.build_url()
        audio_data = self.download(real_url)
        assert audio_data
        __class__.cache[cache_url] = audio_data

    def get_audio_data(self) -> bytes:
        """
        Retrieve the audio data for the segment.

        If the audio data is already cached, it fetches it from the cache;
        otherwise, downloads it from the API and updates the cache.

        Returns:
            The audio data as bytes.
        """
        with self.preload_mutex:
            cache_url = self.build_url()
            if cache_url in __class__.cache:
                logger.debug("Got data for URL '%s' from cache" % (cache_url))
                audio_data = __class__.cache[cache_url]
                assert audio_data
            else:
                real_url = self.build_url()
                audio_data = self.download(real_url)
                assert audio_data
                __class__.cache[cache_url] = audio_data
        return audio_data

    def play(self) -> None:
        """
        Play this segment synchronously using a temporary audio backend.

        Applications that need interruption or multiple utterances should use
        :class:`gspeech.SpeechPlayer` instead.
        """
        audio_data = self.get_audio_data()
        logger.info("Going to speak segment (%s): '%s'" % (self.lang, self))
        backend = MiniaudioBackend()
        try:
            backend.play(audio_data, threading.Event())
            logger.info("Finished speech segment (%s): '%s'" % (self.lang, self))
        finally:
            backend.close()

    def build_url(self) -> str:
        """
        Build the URL for the Google TTS API request based on the segment details.

        Returns:
            The constructed URL as a string.
        """
        params = collections.OrderedDict()
        params["client"] = "tw-ob"
        params["ie"] = "UTF-8"
        params["idx"] = str(self.segment_num)
        if self.segment_count is not None:
            params["total"] = str(self.segment_count)
        params["textlen"] = str(len(self.text))
        params["tl"] = self.lang
        lower_text = self.text.lower()
        params["q"] = lower_text
        return "%s?%s" % (__class__.BASE_URL, urllib.parse.urlencode(params))

    def download(self, url: str) -> bytes:
        """
        Download the audio file for the given URL.

        Args:
            url: The URL to fetch the audio file from.

        Returns:
            The audio file content as bytes.
        """
        logger.debug("Downloading '%s'..." % (url))
        response = __class__.session.get(
            url, headers={"User-Agent": "Mozilla/5.0"}, timeout=3.1
        )
        response.raise_for_status()
        return response.content
