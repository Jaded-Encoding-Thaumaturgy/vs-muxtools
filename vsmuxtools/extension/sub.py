from vstools import vs
from fractions import Fraction
from dataclasses import dataclass
from datetime import timedelta

from muxtools import (
    PathLike,
    ensure_path_exists,
    debug,
    get_absolute_track,
    get_executable,
    TrackType,
    VideoFile,
    VideoTrack,
    MkvTrack,
    TimeScale,
    resolve_timesource_and_scale,
    get_timemeta_from_video,
    TimeType,
)
from muxtools import SubFile as MTSubFile
from muxtools.subtitle import _Line
from muxtools.subtitle.sub import SubFileSelf, LINES
from muxtools.utils.types import TimeSourceT, TimeScaleT

__all__ = ["SubFile"]


@dataclass
class SubFile(MTSubFile):
    """
    Utility class representing a subtitle file with various functions to run on.

    :param file:            Can be a string, Path object or GlobSearch.
                            If the GlobSearch returns multiple results or if a list was passed it will merge them.

    :param container_delay: Set a container delay used in the muxing process later.
    :param source:          The file this sub originates from, will be set by the constructor.
    :param encoding:        Encoding used for reading and writing the subtitle files.
    """

    def truncate_by_video(
        self: SubFileSelf,
        source: PathLike | VideoTrack | MkvTrack | VideoFile | vs.VideoNode,
        timesource: TimeSourceT = None,
        timescale: TimeScaleT = TimeScale.MKV,
    ) -> SubFileSelf:
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

            assert get_absolute_track(file, 0, TrackType.VIDEO, self)
            assert get_executable("ffprobe")

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
