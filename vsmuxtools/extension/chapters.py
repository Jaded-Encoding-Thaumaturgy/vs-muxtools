from fractions import Fraction
from muxtools import parse_chapters_bdmv, PathLike, GlobSearch, Chapter, Chapters as Ch, error, resolve_timesource_and_scale
from muxtools.utils.types import TimeScale, TimeScaleT, TimeSourceT

from ..utils.source import src_file

__all__ = ["Chapters"]


class Chapters(Ch):
    def __init__(
        self,
        chapter_source: src_file | PathLike | GlobSearch | Chapter | list[Chapter],
        timesource: TimeSourceT = None,
        timescale: TimeScaleT = TimeScale.MKV,
        _print: bool = True,
    ) -> None:
        """
        Convenience class for chapters

        :param chapter_source:      Input either src_file/FileInfo, txt with ogm chapters, xml or (a list of) self defined chapters.
        :param timesource:          The source of timestamps/timecodes. For details check the docstring on the type.\n
                                    Will be taken from input if it's a src_file and assume the usual 24 if not.

        :param timescale:           Unit of time (in seconds) in terms of which frame timestamps are represented.\n
                                    For details check the docstring on the type.

        :param _print:              Prints chapters after parsing and after trimming.
        """
        if isinstance(chapter_source, src_file):
            if isinstance(chapter_source.file, list):
                # I'll make a workaround for this soonish
                raise error("Cannot currently parse chapters when splicing multiple files.", self)
            clip_fps = Fraction(chapter_source.src.fps_num, chapter_source.src.fps_den)
            self.timestamps = resolve_timesource_and_scale(timesource if timesource else clip_fps, timescale, caller=self)
            self.chapters = parse_chapters_bdmv(chapter_source.file, clip_fps, chapter_source.src_cut.num_frames, _print)
            if self.chapters and chapter_source.trim:
                self.trim(chapter_source.trim[0] or 0, chapter_source.trim[1] or 0, chapter_source.src_cut.num_frames)
                if _print:
                    print("After trim:")
                    self.print()
        else:
            # TODO: Why does this fail too?
            super().__init__(chapter_source, timesource or Fraction(24000, 1001), timescale, _print)  # type: ignore
