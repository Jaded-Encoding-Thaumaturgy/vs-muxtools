import shlex
import subprocess
from vstools import finalize_clip, vs
from pathlib import Path
from muxtools import get_executable, VideoFile, PathLike, make_output, warn, get_setup_attr, ensure_path, info, get_workdir
from muxtools.utils.env import get_binary_version
from muxtools.utils.dataclass import dataclass, allow_extra

from .base import SupportsQP, VideoEncoder
from .types import LosslessPreset
from ..settings import shift_zones, zones_to_args, norm_zones

from vsmuxtools.utils.source import generate_keyframes, src_file

__all__ = ["x264", "x265", "LosslessX264", "SVTAV1"]


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
            self.zones = norm_zones(clip, self.zones)
            if start_frame:
                self.zones = shift_zones(self.zones, start_frame)
            args.extend(zones_to_args(self.zones, False))
        args.extend(self.get_custom_args() + ["--demuxer", "y4m", "-"])

        process = subprocess.Popen(args, stdin=subprocess.PIPE)
        self.update_process_affinity(process.pid)
        clip.output(process.stdin, y4m=True)
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
            self.zones = norm_zones(clip, self.zones)
            if start_frame:
                self.zones = shift_zones(self.zones, start_frame)
            args.extend(zones_to_args(self.zones, True))
        args.extend(self.get_custom_args() + ["--y4m", "--input", "-"])

        process = subprocess.Popen(args, stdin=subprocess.PIPE)
        self.update_process_affinity(process.pid)
        clip.output(process.stdin, y4m=True)
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
        avc = x264(shlex.join(settings), add_props=self.add_props, resumable=False)
        avc._update_settings(clip, False)
        avc._encode_clip(clip, out, None, 0)
        return VideoFile(out)


@dataclass(config=allow_extra)
class SVTAV1(VideoEncoder):
    """
    Uses SVtAv1EncApp to encode clip to a av1 stream.\n
    Do not use this for high fidelity encoding.\n
    For better explanations of params, check the `--help` of the encoder or the gitlab wiki page.

    :param preset:          Encoder preset. Lower = slower & better
                            The range is -1 to 13 for the regular SVTAV1 and -3 to 13 for SVTAV1-PSY
    :param crf:             Constant rate factor, lower = better
    :param tune:            The tuning metric. None = 2 for SVTAV1 and 3 for SVTAV1-PSY

    :param qp_clip:         Can either be a straight up VideoNode or a SRC_FILE/FileInfo from this package.
                            It is highly recommended to do this so you can force keyframes.
    """

    preset: int = 4
    crf: int | float = 15
    tune: int | None = None
    qp_clip: vs.VideoNode | src_file | None = None

    def __post_init__(self):
        self.executable = get_executable("SvtAv1EncApp")
        if self.get_process_affinity() is False:
            self.affinity = []
        if not self.qp_clip:
            warn("It is highly recommended to force keyframes with this encoder!\nPlease pass a qp_clip param.", self, 2)

    def _make_keyframes_config(self, clip: vs.VideoNode) -> Path | bool:
        out = get_workdir() / "svt_keyframes.cfg"
        if out.exists():
            info("Reusing existing keyframes config.", self)
            return out
        info("Generating keyframes config file...", self)

        keyframes = generate_keyframes(clip)
        if not keyframes:
            return False
        keyframes_str = f"ForceKeyFrames : {'f,'.join([str(i) for i in keyframes])}f"
        with open(out, "w", encoding="utf-8") as f:
            f.write(keyframes_str)

        info("Done", self)
        return out

    def encode(self, clip: vs.VideoNode, outfile: PathLike | None = None) -> VideoFile:
        from vsmuxtools.video.clip_metadata import props_dict, SVT_AV1_RANGES

        clip_props = props_dict(clip, False, SVT_AV1_RANGES)
        output = make_output("svtav1", ext="ivf", user_passed=outfile)
        encoder = get_binary_version(self.executable, r"(SVT-AV1.+?(?:v\d+.\d+.\d[^ ]+|[0-9a-f]{8,40}))", ["--version"])
        tags = dict[str, str](ENCODER=encoder)
        args = [self.executable, "-i", "-", "--output", str(output), "--preset", str(self.preset)]
        if self.qp_clip:
            qp_clip = self.qp_clip if isinstance(self.qp_clip, vs.VideoNode) else self.qp_clip.src_cut
            keyframes_config = self._make_keyframes_config(qp_clip)
            if keyframes_config:
                args.extend(["--keyint", "-1", "-c", str(keyframes_config)])
            else:
                warn("No keyframes found.", self)

        if self.crf:
            args.extend(["--crf", str(self.crf)])

        if self.tune is None:
            self.tune = 3 if "psy" in encoder.lower() else 2

        args.extend(["--tune", str(self.tune)])

        # fmt:off
        args.extend(self.get_custom_args() + [
            "--fps-num", clip_props.get("fps_num"),
            "--fps-denom", clip_props.get("fps_den"),
            "--input-depth", clip_props.get("depth"),
            "--chroma-sample-position", clip_props.get("chromaloc"),
            "--color-primaries", clip_props.get("primaries"),
            "--transfer-characteristics", clip_props.get("transfer"),
            "--matrix-coefficients", clip_props.get("colormatrix"),
            "--color-range", clip_props.get("range")
        ])
        # fmt: on

        process = subprocess.Popen(args, stdin=subprocess.PIPE)
        self.update_process_affinity(process.pid)
        clip.output(process.stdin, y4m=True)
        process.communicate()
        tags.update(ENCODER_SETTINGS=self.get_mediainfo_settings(args))
        return VideoFile(output, tags=tags)
