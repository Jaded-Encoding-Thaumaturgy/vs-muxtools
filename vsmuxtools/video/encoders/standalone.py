import shlex
import subprocess
from vstools import finalize_clip, vs, ChromaLocation
from pathlib import Path
from muxtools import get_executable, VideoFile, PathLike, make_output, warn, get_setup_attr, ensure_path, info, get_workdir, error
from muxtools.utils.env import get_binary_version
from muxtools.utils.dataclass import dataclass, allow_extra
import re
import json
from .base import SupportsQP, VideoEncoder
from .types import LosslessPreset
from .noise import (
    SVTAV1_LIGHT_NOISE_TABLE_FULL,
    SVTAV1_LIGHT_NOISE_TABLE_LIMITED,
    x265_write_light_noise_table_full,
    x265_write_light_noise_table_limited,
)
from ..settings import shift_zones, zones_to_args, norm_zones
from ..clip_metadata import props_dict, SVT_AV1_RANGES

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
        assert process.stdin
        clip.output(process.stdin, y4m=True)
        process.communicate()
        return out


@dataclass(config=allow_extra)
class x265(SupportsQP):
    """
    Encodes your clip to an hevc/h265 file using x265.

    :param settings:            This will by default try to look for an `x265_settings` file in your cwd.\n
                                If it doesn't find one it will warn you and resort to the default settings_builder preset.\n
                                You can either pass settings as usual or a filepath here.\n
                                If the filepath doesn't exist it will assume you passed actual settings and pass those to the encoder.

    :param zones:               With this you can tweak settings of specific regions of the video.\n
                                In x265 you're basically limited to a flat bitrate multiplier or force QP ("q")\n
                                For example (100, 300, "b", 1.2) or [(100, 300, "q", 12), (500, 750, 1.3)]\n
                                If the third part is not a string it will assume a bitrate multiplier (or "b")

    :param qp_file:             Here you can pass a bool to en/disable or an existing filepath for one.
    :param qp_clip:             Can either be a straight up VideoNode or a SRC_FILE/FileInfo from this package.\n
                                If neither a clip or a file are given it will simply skip.
                                If only a clip is given it will generate one.

    :param add_props:           This will explicitly add all props taken from the clip to the command line.\n
                                This will be disabled by default if you are using a file and otherwise enabled.\n
                                Files can have their own tokens like in vs-encode/vardautomation that will be filled in.

    :param light_photon_noise:  Add a layer of light photon noise on top, serving a similar role as a light regrain / dither.\n
                                This feature is supported on mpv but not on a lot of other players, which means it shouldn't replace your main regrain.\n
                                Automatically disabled when either `--aom-film-grain` or `--film-grain` is used.\n
                                Do note that x265 will log the path to the file containing the grain pattern so, if for whatever reason that can't be a relative one,
                                you need to check the mediainfo and make sure it doesn't contain anything sensitive.\n
                                **This is unlikely to happen if you don't mangle the muxtools workdir yourself.**

    :param sar:                 Here you can pass your Pixel / Sample Aspect Ratio. This will overwrite whatever is in the clip if passed.
    :param resumable:           Enable or disable resumable encodes. Very useful for people that have scripts that crash their PC (skill issue tbh)
    :param csv:                 Either a bool to enable or disable csv logging or a Filepath for said csv.
    """

    resumable: bool = True
    csv: bool | PathLike = True
    x265 = True
    light_photon_noise: bool = False

    def __post_init__(self):
        self.executable = get_executable("x265")
        self._init_settings(self.x265)

    def _encode_clip(self, clip: vs.VideoNode, out: Path, qpfile: str | None, start_frame: int = 0) -> Path:
        args = [self.executable, "-o", str(out.resolve())]
        clip_props = props_dict(clip, False)
        if self.csv:
            if isinstance(self.csv, bool):
                show_name = get_setup_attr("show_name", "")
                csv_file = Path(show_name + f"{'_' if show_name else ''}log_x265.csv").resolve()
            else:
                csv_file = ensure_path(self.csv, self)
            args.extend(["--csv", str(csv_file)])
        if qpfile:
            args.extend(["--qpfile", qpfile])

        if self.light_photon_noise:
            if not any(key in self.get_custom_args_dict() for key in {"aom_film_grain", "film_grain"}):
                fgs_table = get_workdir() / "x265_grain.bin"
                if clip_props.get("range") == "limited":
                    x265_write_light_noise_table_limited(fgs_table, clip.num_frames - start_frame)
                else:
                    x265_write_light_noise_table_full(fgs_table, clip.num_frames - start_frame)
                try:
                    fgs_table = fgs_table.relative_to(Path.cwd())
                except ValueError:
                    warn(f"The following grain table file path will be visible in the mediainfo:\n{str(fgs_table)}", self)
                self.update_custom_args(aom_film_grain=str(fgs_table))

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
        assert process.stdin
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

    You can use the available `settings_builder`s for a set of default parameters.
    For better explanations of parameters, check the `Docs/Parameters.md` file in encoder's GitHub or GitLab.

    Defaults to `--preset 2` if no `--preset` or `--speed` given.
    Defaults to `--crf 22` if no `--crf` or `--quality` given.

    :param sd_clip:            Perform scene detection for the encoder.
                               Can either be a straight up VideoNode or a SRC_FILE/FileInfo from this package.
                               It is recommended to use this scene detection for 5fish/SVT-AV1-PSY with the `--balancing-q-bias` system, while for SVT-AV1-Essential, you can rely on its own internal scene detection.
    :param light_photon_noise: Add a layer of light photon noise on top, serving a similar role as a light regrain / dither.
                               For a layer of noise with different strength or coarseness, you can generate it yourself following the guide available in AV1 weeb server.
                               On supported forks, you may also use `--photon-noise` parameter to apply a basic photon noise with configurable strength but not coarseness.
                               Automatically disabled when either `--film-grain`, `--fgs-table`, or `--photon-noise` are used.
    """

    sd_clip: vs.VideoNode | src_file | None = None
    light_photon_noise: bool = True
    _encoder_id: str | None = None
    _settings_builder_id: str | None = None

    def __post_init__(self):
        self.executable = get_executable("SvtAv1EncApp")
        if self.get_process_affinity() is False:
            self.affinity = []

        self._encoder_id = get_binary_version(self.executable, r"(.+) \((?:release|debug)\)", ["--version"])

        if not self._encoder_id:
            raise error("Couldn't parse SvtAv1EncApp version!", self)

        if self._settings_builder_id is not None:
            if not re.match(self._settings_builder_id, self._encoder_id):
                warn(f"Unexpected encoder version: {self._encoder_id}.", self)
                warn(f"Encoder version expected by the settings_builder: {self._settings_builder_id}.", self, 2)

        if not self.sd_clip and not self._encoder_id.startswith("SVT-AV1-Essential") and "_c" not in self.get_custom_args_dict():
            warn("Providing a clip or a file for scene detection is recommended for SVT-AV1.", self, 2)

    def encode(self, clip: vs.VideoNode, outfile: PathLike | None = None) -> VideoFile:
        if clip.format.bits_per_sample > 10:
            warn("SVT-AV1 doesn't support a bit depth over 10.\nClip will be dithered to 10 bit.", self, 2)
            clip = finalize_clip(clip, 10)
        elif clip.format.bits_per_sample < 10:
            warn("SVT-AV1 works best at 10 bit.\nClip will be converted to 10 bit", self, 2)
            clip = finalize_clip(clip, 10)

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
        args = [self.executable, "--input", "-", "--output", str(output)]

        if not any(key in self.get_custom_args_dict() for key in {"preset", "speed"}):
            self.update_custom_args(preset=2)
        if not any(key in self.get_custom_args_dict() for key in {"crf", "quality", "qp", "rc"}):
            self.update_custom_args(crf=22)

        # sd_clip
        if self.sd_clip:
            if "force_key_frames" in self.get_custom_args_dict():
                raise error("Scene detection from `sd_clip` can't be applied when `--force-key-frames` encoder parameter is already specified.", self)

            if "Essential" in str(self._encoder_id):
                info(
                    "Disabling built-in scene change detection of SVT-AV1-Essential in favor of muxtools implementation.\nDon't pass 'sd_clip' if this is undesirable.",
                    self,
                )

            self.update_custom_args(keyint=0, scd=0)

            sd_clip = self.sd_clip if isinstance(self.sd_clip, vs.VideoNode) else self.sd_clip.src_cut
            if sd_clip.num_frames != clip.num_frames:
                raise error("Scene detection clip `sd_clip` has different length than the `clip` being encoded", self)

            cache = get_workdir() / "svt_av1_scene_detection_cache.json"

            try:
                with cache.open("r") as cache_f:
                    cache_config = json.load(cache_f)

                assert cache_config["frames"] == sd_clip.num_frames
                assert isinstance(cache_config["scenecuts"], list)
                assert all(isinstance(f, int) for f in cache_config["scenecuts"])

                info("Reusing existing scene detection.", self)
                keyframes = cache_config["scenecuts"]
            except Exception:
                info("Performing scene detection...", self)
                keyframes = generate_svt_av1_keyframes(sd_clip)

                cache_config = {
                    "frames": sd_clip.num_frames,
                    "scenecuts": keyframes,
                }
                with cache.open("w") as cache_f:
                    json.dump(cache_config, cache_f)

                info("Scene detection complete.", self)

            keyframes_str = "f,".join([str(i) for i in keyframes]) + "f"
            if "_c" not in self.get_custom_args_dict():
                keyframes_file = get_workdir() / "svt_av1_keyframes.cfg"
                with keyframes_file.open("w", encoding="utf-8") as keyframes_f:
                    keyframes_f.write(f"ForceKeyFrames : {keyframes_str}\n")

                self.update_custom_args(_c=str(keyframes_file))
            else:
                info("Attempting to use commandline parameter to specify keyframes since `-c` is already used...", self)
                self.update_custom_args(force_key_frames=keyframes_str)

        # light_photon_noise
        if self.light_photon_noise:
            if not any(key in self.get_custom_args_dict() for key in {"fgs_table", "film_grain", "photon_noise"}):
                fgs_table = get_workdir() / "svt_av1_fgs.tbl"
                with fgs_table.open("w", encoding="utf-8") as fgs_table_f:
                    if clip_props.get("range") == SVT_AV1_RANGES[1]:
                        fgs_table_f.write(SVTAV1_LIGHT_NOISE_TABLE_LIMITED)
                    else:
                        fgs_table_f.write(SVTAV1_LIGHT_NOISE_TABLE_FULL)

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
        assert process.stdin
        clip.output(process.stdin, y4m=True)
        process.communicate()

        tags.update(ENCODER_SETTINGS=self.get_mediainfo_settings(args))
        return VideoFile(output, tags=tags)
