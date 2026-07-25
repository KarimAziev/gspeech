import logging
import re
import string
import sys
import unicodedata
from io import BufferedWriter
from os import PathLike
from typing import TYPE_CHECKING, Callable, Generator, Iterator, List, Optional, Union

from gspeech.speech_segment import SpeechSegment

if TYPE_CHECKING:
    from gspeech.player import SpeechPlayer

logger = logging.getLogger(__name__)


class Speech:
    """
    Handles text-to-speech processing and audio playback.
    """

    CLEAN_MULTIPLE_SPACES_REGEX = re.compile(r"\s{2,}")
    MAX_SEGMENT_SIZE = 200

    def __init__(self, text: str, lang: str):
        self.text = self.clean_spaces(text)
        self.lang = lang

    def __iter__(self) -> Iterator[SpeechSegment]:
        """
        Return an iterator that generates speech segments.
        """
        return self.__next__()

    def __next__(self) -> Generator[SpeechSegment, None, None]:
        """
        Generate speech segments from the text.

        Segments are produced by splitting the input text while taking into account spaces, punctuation,
        and a maximum segment size constraint.
        """
        if self.text == "-":
            if sys.stdin.isatty():
                logger.error("Stdin is not a pipe")
                return
            while True:
                new_line = sys.stdin.readline()
                if not new_line:
                    return
                segments = __class__.split_text(new_line)
                for segment_num, segment in enumerate(segments):
                    yield SpeechSegment(segment, self.lang, segment_num, len(segments))

        else:
            segments = __class__.split_text(self.text)
            for segment_num, segment in enumerate(segments):
                yield SpeechSegment(segment, self.lang, segment_num, len(segments))

    @staticmethod
    def find_last_char_index_matching(
        text: str, func: Callable[[str], bool]
    ) -> Optional[int]:
        """
        Find the index of the last character in a string that matches a given condition.

        The condition is determined by a callable `func` that takes a character as input
        and returns a boolean.
        """
        for i in range(len(text) - 1, -1, -1):
            if func(text[i]):
                return i

    @staticmethod
    def split_text(text: str) -> List[str]:
        """
        Split a string into subsegments, each of which does not exceed the maximum segment size.

        The splitting process prioritizes breaking at punctuation, whitespace, or other non-alphanumeric
        characters, ensuring meaningful boundaries within the text.
        """
        segments: List[str] = []
        remaining_text = __class__.clean_spaces(text)

        while len(remaining_text) > __class__.MAX_SEGMENT_SIZE:
            cur_text = remaining_text[: __class__.MAX_SEGMENT_SIZE]

            split_idx = __class__.find_last_char_index_matching(
                cur_text,
                # https://en.wikipedia.org/wiki/Unicode_character_property#General_Category
                lambda x: unicodedata.category(x) in ("Ps", "Pe", "Pi", "Pf", "Po"),
            )
            if split_idx is None:
                # try to split at whitespace
                split_idx = __class__.find_last_char_index_matching(
                    cur_text, lambda x: unicodedata.category(x).startswith("Z")
                )
            if split_idx is None:
                # try to split at anything not a letter or number
                split_idx = __class__.find_last_char_index_matching(
                    cur_text, lambda x: unicodedata.category(x)[0] not in ("L", "N")
                )
            if split_idx is None:
                # split at the last char
                split_idx = __class__.MAX_SEGMENT_SIZE - 1

            new_segment = cur_text[: split_idx + 1].rstrip()
            segments.append(new_segment)
            remaining_text = remaining_text[split_idx + 1 :].lstrip(
                string.whitespace + string.punctuation
            )

        if remaining_text:
            segments.append(remaining_text)

        return segments

    @staticmethod
    def clean_spaces(dirty_string: str) -> str:
        """
        Normalize spacing in a string by removing consecutive spaces and trimming whitespace.

        This method replaces newlines and tabs with single spaces and ensures the string
        is stripped of leading and trailing whitespace.
        """
        return __class__.CLEAN_MULTIPLE_SPACES_REGEX.sub(
            " ", dirty_string.replace("\n", " ").replace("\t", " ").strip()
        )

    def play(self, player: Optional["SpeechPlayer"] = None) -> None:
        """
        Play the text synchronously.

        Pass a shared :class:`gspeech.SpeechPlayer` when the caller needs to
        interrupt this operation from another thread. Without one, a temporary
        player is created and closed automatically.
        """
        from gspeech.player import SpeechPlayer, SpeechPolicy, SpeechStatus

        owns_player = player is None
        active_player = player or SpeechPlayer()
        try:
            if self.text == "-":
                for segment in self:
                    result = active_player.play(
                        Speech(segment.text, self.lang),
                        policy=SpeechPolicy.ENQUEUE,
                    )
                    if (
                        result.status is SpeechStatus.FAILED
                        and result.error is not None
                    ):
                        raise result.error
                return

            result = active_player.play(self)
            if result.status is SpeechStatus.FAILED and result.error is not None:
                raise result.error
        finally:
            if owns_player:
                active_player.close()

    def save(self, path: Union[str, int, PathLike]) -> None:
        """
        Save the synthesized speech audio to a file.

        The output file will be in MP3 format.
        """
        with open(path, "wb") as f:
            self.savef(f)

    def savef(self, file: BufferedWriter) -> None:
        """
        Write the synthesized speech audio into a file-like object.

        The file object must be writable, and the data will be written in binary format.
        """
        for segment in self:
            file.write(segment.get_audio_data())
