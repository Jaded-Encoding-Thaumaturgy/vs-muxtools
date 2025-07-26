from vstools import vs
from fractions import Fraction
from dataclasses import dataclass
from datetime import timedelta
from typing_extensions import Self

from muxtools import (
    PathLike,
    ensure_path_exists,
    debug,
    ParsedFile,
    TrackType,
    VideoFile,
    VideoTrack,
    MkvTrack,
    TimeScale,
    resolve_timesource_and_scale,
    get_timemeta_from_video,
    TimeType,
    error,
    warn,
)
from muxtools import SubFile as MTSubFile, SubFilePGS as MTSubFilePGS
from muxtools.subtitle import _Line
from muxtools.subtitle.sub import LINES
from muxtools.utils.types import TimeSourceT, TimeScaleT

from ..utils.source import src_file

__all__ = ["SubFile", "SubFilePGS"]


@dataclass
class SubFile(MTSubFile):
    """
    Utility class representing an ASS/SSA subtitle file with various functions to run on.

    :param file:            Can be a string, Path object or GlobSearch.
                            If the GlobSearch returns multiple results or if a list was passed it will merge them.

    :param container_delay: Set a container delay used in the muxing process later.
    :param source:          The file this sub originates from, will be set by the constructor.
    :param encoding:        Encoding used for reading and writing the subtitle files.
    """

    def truncate_by_video(
        self,
        source: PathLike | VideoTrack | MkvTrack | VideoFile | vs.VideoNode,
        timesource: TimeSourceT = None,
        timescale: TimeScaleT = TimeScale.MKV,
    ) -> Self:
        """
        Removes lines that start after the video ends and trims lines that extend past it.

        :param source:          Can be any video file or a VideoNode
        :param timesource:      The source of timestamps/timecodes. For details check the docstring on the type.
        :param timescale:       Unit of time (in seconds) in terms of which frame timestamps are represented.\n
                                For details check the docstring on the type.
        """

        if isinstance(source, vs.VideoNode):
            frames = source.num_frames
            if not timesource:
                timesource = Fraction(source.fps_num, source.fps_den)
            resolved_ts = resolve_timesource_and_scale(timesource, timescale, allow_warn=False, caller=self)
        else:
            if isinstance(source, VideoTrack) or isinstance(source, MkvTrack) or isinstance(source, VideoFile):
                file = ensure_path_exists(source.file, self)
            else:
                file = ensure_path_exists(source, self)

            parsed = ParsedFile.from_file(file, self)

            assert parsed.find_tracks(type=TrackType.VIDEO, error_if_empty=True, caller=self)[0]

            meta = get_timemeta_from_video(file, caller=self)
            frames = len(meta.pts)
            if not timesource:
                timesource = meta
                timescale = meta.timescale
            resolved_ts = resolve_timesource_and_scale(timesource, timescale, allow_warn=False, caller=self)

        cutoff = timedelta(milliseconds=resolved_ts.frame_to_time(frames + 1, TimeType.START, 2, True) * 10)

        def filter_lines(lines: LINES):
            removed = 0
            trimmed = 0
            new_list = list[_Line]()
            for line in lines:
                if line.start > cutoff:
                    removed += 1
                    continue
                if line.end > cutoff:
                    line.end = timedelta(milliseconds=resolved_ts.frame_to_time(frames, TimeType.END, 2, True) * 10)
                    trimmed += 1
                new_list.append(line)

            if removed or trimmed:
                if removed:
                    debug(f"Removed {removed} line{'s' if removed != 1 else ''} that started past the video", self)
                if trimmed:
                    debug(f"Trimmed {trimmed} line{'s' if trimmed != 1 else ''} that extended past the video", self)

            return new_list

        return self.manipulate_lines(filter_lines)


@dataclass
class SubFilePGS(MTSubFilePGS):
    """
    Utility class representing a PGS/SUP subtitle file.

    :param file:            Can be a string, Path object or GlobSearch.
    :param container_delay: Set a container delay used in the muxing process later.
    :param source:          The file this sub originates from, will be set by the constructor.
    """

    @classmethod
    def extract_from(cls: type[Self], fileIn: PathLike | src_file, track: int = 0, preserve_delay: bool = False, quiet: bool = True) -> Self:
        """
        Extract a PGS subtitle track from a file using ffmpeg.\n

        :param fileIn:          The input file to extract from.
        :param track:           The track number to extract.
        :param preserve_delay:  If True, the container delay will be preserved.
        :param quiet:           If True, suppresses ffmpeg output.
        :return:                An instance of SubFilePGS containing the extracted subtitle.
        """
        f = fileIn
        if isinstance(f, src_file):
            if isinstance(f.file, list):
                # I'll make a workaround for this soonish
                raise error("Cannot currently parse chapters when splicing multiple files.", cls.__name__)
            f = f.file
        new = super().extract_from(
            f,
            track=track,
            preserve_delay=preserve_delay,
            quiet=quiet,
        )
        if isinstance(fileIn, src_file) and fileIn.trim:
            if fileIn.trim[0]:
                debug(f"Shifting extracted subtitle by -{fileIn.trim[0]} frames...", cls.__name__)
                new = new.shift(-fileIn.trim[0], timesource=fileIn.file, quiet=quiet)
            if fileIn.trim[1]:
                warn("Trimming is currently not supported for PGS subtitles.", cls.__name__)
        return new
