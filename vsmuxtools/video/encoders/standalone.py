import shlex
import subprocess
from vstools import finalize_clip, vs, ChromaLocation
from pathlib import Path
from muxtools import get_executable, VideoFile, PathLike, make_output, warn, get_setup_attr, ensure_path, info, get_workdir, error
from muxtools.utils.env import get_binary_version
from muxtools.utils.dataclass import dataclass, allow_extra
import numpy as np

from .base import SupportsQP, VideoEncoder
from .types import LosslessPreset
from ..settings import shift_zones, zones_to_args, norm_zones

from vsmuxtools.utils.source import generate_svt_av1_keyframes, src_file

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

    def _encode_clip(self, clip: vs.VideoNode, out: Path, qpfile: str | None, start_frame: int = 0) -> Path:
        args = [self.executable, "-o", str(out.resolve())]
        if qpfile:
            args.extend(["--qpfile", qpfile])
        if self.settings:
            args.extend(self.settings if isinstance(self.settings, list) else shlex.split(str(self.settings)))
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

    def _encode_clip(self, clip: vs.VideoNode, out: Path, qpfile: str | None, start_frame: int = 0) -> Path:
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
            args.extend(self.settings if isinstance(self.settings, list) else shlex.split(str(self.settings)))
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
    Uses SvtAv1EncApp to encode clip to an AV1 stream.

    Do not use this for high fidelity encoding.

    You can use the available `settings_builder`s for a set of default parameters.\n
    For better explanations of parameters, check the `Docs/Parameters.md` file in encoder's GitHub or GitLab.

    Defaults to preset 2 if no preset or quality params given.\n
    Defaults to crf 22 if no ratecontrol related params given.

    :param sd_clip:         Perform scene detection for the encoder.
                            Can either be a straight up VideoNode or a SRC_FILE/FileInfo from this package.\n
                            It is highly recommended for you to provide a clip or a file here for scene detection, as most SVT-AV1 forks don't have scene detection at all.\n
                            The only exception is SVT-AV1-Essential which can perform its own scene detection.
    :param photon_noise:    Add a basic layer of light photon noise on top, serving a similar role as regrain / dither.\n
                            For a layer of noise with different strength or coarseness, you can generate it yourself following the guide available in AV1 weeb server.
    """

    sd_clip: vs.VideoNode | src_file | None = None
    photon_noise: bool = True
    _encoder_id: str | None = None
    _settings_builder_id: str | None = None

    def __post_init__(self):
        self.executable = get_executable("SvtAv1EncApp")
        if self.get_process_affinity() is False:
            self.affinity = []

        self._encoder_id = get_binary_version(self.executable, r"(\S+ v\S+) \((?:release|debug)\)", ["--version"])

        if not self._encoder_id:
            raise error("Couldn't parse SvtAv1EncApp version!", self)

        if self._settings_builder_id is not None:
            if not self._encoder_id.startswith(self._settings_builder_id):
                warn(f"Unexpected encoder version: {self._encoder_id}.", self)
                warn(f"Encoder version expected by the settings_builder: {self._settings_builder_id}.", self, 2)

        if not self.sd_clip and not self._encoder_id.startswith("SVT-AV1-Essential") and "_c" not in self.get_custom_args_dict():
            warn(
                "Providing a clip or a file for scene detection is highly recommended, as most SVT-AV1 versions don't have proper scene detection.",
                self,
                2,
            )

    def encode(self, clip: vs.VideoNode, outfile: PathLike | None = None) -> VideoFile:
        if clip.format.bits_per_sample > 10:
            warn("SVT-AV1 doesn't support a bit depth over 10.\nClip will be dithered to 10 bit.", self, 2)
            clip = finalize_clip(clip, 10)
        elif clip.format.bits_per_sample < 10:
            warn("SVT-AV1 works best at 10 bit.\nClip will be converted to 10 bit", self, 2)
            clip = finalize_clip(clip, 10)

        from vsmuxtools.video.clip_metadata import props_dict, SVT_AV1_RANGES

        clip_props = props_dict(clip, False, SVT_AV1_RANGES)
        match int(clip_props["chromaloc"]):
            case ChromaLocation.LEFT.value:
                cloc = "left"
            case ChromaLocation.TOP_LEFT.value:
                cloc = "topleft"
            case _:
                raise error("AV1 only supports LEFT and TOPLEFT chroma locations!", self)

        output = make_output("svtav1", ext="ivf", user_passed=outfile)

        tags = dict[str, str](ENCODER=str(self._encoder_id))
        args = [self.executable, "-i", "-", "--output", str(output)]

        if not any(key in self.get_custom_args_dict() for key in {"preset", "speed"}):
            self.update_custom_args(preset=2)
        if not any(key in self.get_custom_args_dict() for key in {"crf", "quality", "qp", "rc"}):
            self.update_custom_args(crf=22)

        # sd_clip
        if self.sd_clip:
            if "force_key_frames" in self.get_custom_args_dict():
                raise error("Scene detection from `sd_clip` can't be applied when `--force-key-frames` encoder parameter is already specified.", self)

            sd_clip = self.sd_clip if isinstance(self.sd_clip, vs.VideoNode) else self.sd_clip.src_cut

            cache = get_workdir() / "svt_av1_scene_detection_cache.npy"

            if not cache.exists():
                info("Performing scene detection...", self)
                keyframes = generate_svt_av1_keyframes(sd_clip)
                np.save(cache, keyframes)
                info("Scene detection complete.", self)
            else:
                info("Reusing existing scene detection.", self)

            keyframes = np.load(cache)
            keyframes_str = "f,".join([str(i) for i in keyframes]) + "f"

            if "_c" not in self.get_custom_args_dict():
                keyframes_file = get_workdir() / "svt_av1_keyframes.cfg"
                with keyframes_file.open("w", encoding="utf-8") as keyframes_f:
                    keyframes_f.write(f"ForceKeyFrames : {keyframes_str}\n")

                self.update_custom_args(_c=str(keyframes_file))
            else:
                info("Attempting to use commandline parameter to specify keyframes since `-c` is already used...", self)
                self.update_custom_args(force_key_frames=keyframes_str)

            self.update_custom_args(keyint=-1)

        # photon_noise
        if self.photon_noise:
            if not any(key in self.get_custom_args_dict() for key in {"fgs_table", "film_grain"}):
                fgs_table = get_workdir() / "svt_av1_fgs.tbl"
                with fgs_table.open("w", encoding="utf-8") as fgs_table_f:
                    fgs_table_f.write("""filmgrn1
E 0 18446744073709551615 1 787 1
	p 3 7 0 8 0 1 128 192 256 128 192 256
	sY 14 0 4 20 3 39 3 59 3 78 3 98 3 118 3 137 3 157 3 177 4 196 4 216 4 235 4 255 5
	sCb 0
	sCr 0
	cY 3 4 3 3 3 3 3 3 4 2 0 2 3 3 3 2 -7 -19 -4 1 3 2 0 -18
	cCb -3 9 -15 20 -6 0 0 9 -22 32 -50 10 -3 1 -15 32 -61 70 -26 -1 -2 17 -40 59 11
	cCr -3 9 -15 20 -6 0 1 9 -21 32 -50 10 -3 0 -14 31 -61 71 -26 -1 -1 17 -40 58 11
""")

                self.update_custom_args(fgs_table=str(fgs_table))

        # user parameters
        args.extend(self.get_custom_args())

        # props
        # fmt:off
        args.extend([
            "--fps-num", clip_props.get("fps_num"),
            "--fps-denom", clip_props.get("fps_den"),
            "--input-depth", clip_props.get("depth"),
            "--chroma-sample-position", cloc,
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
