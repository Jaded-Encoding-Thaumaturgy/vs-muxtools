import shlex
import subprocess
from vstools import finalize_clip, vs
from pathlib import Path
from muxtools import get_executable, VideoFile, PathLike, make_output, warn, get_setup_attr, ensure_path
from muxtools.utils.dataclass import dataclass, allow_extra

from .base import SupportsQP, VideoEncoder
from vsmuxtools.utils.types import LosslessPreset
from vsmuxtools.video.settings import shift_zones, zones_to_args

__all__ = ["x264", "x265", "LosslessX264"]


@dataclass(config=allow_extra)
class x264(SupportsQP):
    """
    Encodes your clip to an avc/h264 file using x264.

    :param settings:            This will by default try to look for an `x264_settings` file in your cwd.
                                If it doesn't find one it will warn you and resort to the default settings_builder preset.
                                You can either pass settings as usual or a filepath here.
                                If the filepath doesn't exist it will assume you passed actual settings and pass those to the encoder.

    :param zones:               With this you can tweak settings of specific regions of the video.
                                In x264 this includes but is not limited to CRF.
                                For example (100, 300, "crf", 12) or [(100, 300, "crf", 12), (500, 750, 1.3)]
                                If the third part is not a string it will assume a bitrate multiplier (or "b")

    :param qp_file:             Here you can pass a bool to en/disable or an existing filepath for one.
    :param qp_clip:             Can either be a straight up VideoNode or a SRC_FILE/FileInfo from this package.
                                If neither a clip or a file are given it will simply skip.
                                If only a clip is given it will generate one.

    :param add_props:           This will explicitly add all props taken from the clip to the command line.
                                This will be disabled by default if you are using a file and otherwise enabled.
                                Files can have their own tokens like in vs-encode/vardautomation that will be filled in.

    :param sar:                 Here you can pass your Pixel / Sample Aspect Ratio. This will overwrite whatever is in the clip if passed.
    :param resumable:           Enable or disable resumable encodes. Very useful for people that have scripts that crash their PC (skill issue tbh)
    """

    resumable: bool = True
    x265 = False

    def __post_init__(self):
        self.executable = get_executable("x264")
        self._init_settings(self.x265)

    def _encode_clip(self, clip: vs.VideoNode, out: Path, qpfile: str, start_frame: int = 0) -> Path:
        args = [self.executable, "-o", str(out.resolve())]
        if qpfile:
            args.extend(["--qpfile", qpfile])
        if self.settings:
            args.extend(self.settings if isinstance(self.settings, list) else shlex.split(self.settings))
        if self.zones:
            if start_frame:
                self.zones = shift_zones(self.zones, start_frame)
            args.extend(zones_to_args(self.zones, False))
        args.extend(self.get_custom_args() + ["--demuxer", "y4m", "-"])

        process = subprocess.Popen(args, stdin=subprocess.PIPE)
        clip.output(process.stdin, y4m=True, progress_update=lambda x, y: self._update_progress(x, y))
        process.communicate()
        return out


@dataclass(config=allow_extra)
class x265(SupportsQP):
    """
    Encodes your clip to an hevc/h265 file using x265.

    :param settings:            This will by default try to look for an `x265_settings` file in your cwd.
                                If it doesn't find one it will warn you and resort to the default settings_builder preset.
                                You can either pass settings as usual or a filepath here.
                                If the filepath doesn't exist it will assume you passed actual settings and pass those to the encoder.

    :param zones:               With this you can tweak settings of specific regions of the video.
                                In x265 you're basically limited to a flat bitrate multiplier or force QP ("q")
                                For example (100, 300, "b", 1.2) or [(100, 300, "q", 12), (500, 750, 1.3)]
                                If the third part is not a string it will assume a bitrate multiplier (or "b")

    :param qp_file:             Here you can pass a bool to en/disable or an existing filepath for one.
    :param qp_clip:             Can either be a straight up VideoNode or a SRC_FILE/FileInfo from this package.
                                If neither a clip or a file are given it will simply skip.
                                If only a clip is given it will generate one.

    :param add_props:           This will explicitly add all props taken from the clip to the command line.
                                This will be disabled by default if you are using a file and otherwise enabled.
                                Files can have their own tokens like in vs-encode/vardautomation that will be filled in.

    :param sar:                 Here you can pass your Pixel / Sample Aspect Ratio. This will overwrite whatever is in the clip if passed.
    :param resumable:           Enable or disable resumable encodes. Very useful for people that have scripts that crash their PC (skill issue tbh)
    :param csv:                 Either a bool to enable or disable csv logging or a Filepath for said csv.
    """

    resumable: bool = True
    csv: bool | PathLike = True
    x265 = True

    def __post_init__(self):
        self.executable = get_executable("x265")
        self._init_settings(self.x265)

    def _encode_clip(self, clip: vs.VideoNode, out: Path, qpfile: str, start_frame: int = 0) -> Path:
        args = [self.executable, "-o", str(out.resolve())]
        if self.csv:
            if isinstance(self.csv, bool):
                show_name = get_setup_attr("show_name", "")
                csv_file = Path(show_name + f"{'_' if show_name else ''}log_x265.csv").resolve()
            else:
                csv_file = ensure_path(self.csv, self)
            args.extend(["--csv", str(csv_file)])
        if qpfile:
            args.extend(["--qpfile", qpfile])
        if self.settings:
            args.extend(self.settings if isinstance(self.settings, list) else shlex.split(self.settings))
        if self.zones:
            if start_frame:
                self.zones = shift_zones(self.zones, start_frame)
            args.extend(zones_to_args(self.zones, True))
        args.extend(self.get_custom_args() + ["--y4m", "-"])

        process = subprocess.Popen(args, stdin=subprocess.PIPE)
        clip.output(process.stdin, y4m=True, progress_update=lambda x, y: self._update_progress(x, y))
        process.communicate()
        return out


@dataclass(config=allow_extra)
class LosslessX264(VideoEncoder):
    """
    Uses x264 to encode clip to a lossless avc stream.

    :param preset:          Can either be a string of some x264 preset or any of the 3 predefined presets.
    :param settings:        Any other settings you might want to pass. Entirely optional.
    :param add_props:       This will explicitly add all props taken from the clip to the command line.
    """

    preset: str | LosslessPreset = LosslessPreset.MIDDLEGROUND
    settings: str | None = None
    add_props: bool = True

    def encode(self, clip: vs.VideoNode, outfile: PathLike | None = None) -> VideoFile:
        out = make_output("lossless", "264", user_passed=outfile)
        match self.preset:
            case LosslessPreset.SPEED:
                preset = "ultrafast"
            case LosslessPreset.COMPRESSION:
                preset = "veryslow"
            case LosslessPreset.MIDDLEGROUND:
                preset = "medium"
            case _:
                preset = self.preset
        settings = ["--preset", preset, "--qp", "0"] + self.get_custom_args()
        if clip.format.bits_per_sample > 10:
            warn("This encoder does not support a bit depth over 10.\nClip will be dithered to 10 bit.", self, 2)
            clip = finalize_clip(clip, 10)

        if self.settings:
            settings.extend(shlex.split(self.settings))
        avc = x264(settings, add_props=self.add_props, resumable=False)
        avc._update_settings(clip, False)
        avc._encode_clip(clip, out, None, 0)
        return VideoFile(out)
