import shlex
from vstools import finalize_clip, vs, get_video_format
from pathlib import Path
from dataclasses import dataclass
from abc import ABC, abstractmethod
from muxtools import ensure_path_exists, VideoFile, PathLike, make_output, info, warn, error, get_executable
from muxtools.utils.dataclass import CLIKwargs

from .types import Zone
from ..resumable import merge_parts, parse_keyframes
from ..settings import file_or_default, sb264, sb265
from ..clip_metadata import fill_props, props_args, props_dict
from vsmuxtools.utils.source import generate_qp_file, src_file

__all__ = ["VideoEncoder", "FFMpegEncoder", "SupportsQP"]


@dataclass
class VideoEncoder(CLIKwargs, ABC):
    resumable = False

    @abstractmethod
    def encode(self, clip: vs.VideoNode, outfile: PathLike | None = None) -> VideoFile:
        """
        To actually run the encode.

        :param clip:            Your videonode
        :param outfile:         Can be a custom output file or directory.
                                The correct extension will automatically be appended.

        Returns a VideoFile object.
        If you're only interested in the path you can just do `VideoFile.file`.
        """
        ...

    def _update_progress(self, current_frame, total_frames):
        print(f"\rVapoursynth: {current_frame} / {total_frames} " f"({100 * current_frame // total_frames}%) || Encoder: ", end="")


@dataclass
class FFMpegEncoder(VideoEncoder, ABC):
    def __post_init__(self):
        self.executable = get_executable("ffmpeg")

    def _default_args(self) -> list[str]:
        return [self.executable, "-v", "quiet", "-stats"]

    def _pixfmt_for_clip(self, clip: vs.VideoNode) -> str:
        videoformat = get_video_format(clip)
        if videoformat.color_family != vs.YUV:
            raise error("Only YUV input allowed for FFMPEG pipes/encoders!", self)

        allowed_depths = range(8, 18, 2)
        if videoformat.bits_per_sample not in allowed_depths:
            raise error(f"Only the following bitdepths are allowed: {', '.join([str(x) for x in allowed_depths])}", self)

        formatname = videoformat.name.replace("P8", "P").lower()
        return formatname + "le" if videoformat.bits_per_sample > 8 else formatname

    def input_args(self, clip: vs.VideoNode) -> tuple[list[str], list[str]]:
        props = props_dict(clip, True)
        # fmt: off
        prop_args = [
            "-r", f"{props.get('fps_num')}/{props.get('fps_den')}",
            "-color_range", props.get("range"),
            "-colorspace", props.get("colormatrix"),
            "-color_primaries", props.get("primaries"),
            "-color_trc", props.get("transfer"),
            "-chroma_sample_location", props.get("chromaloc"),
        ]
        input_arguments = prop_args + ["-f", "yuv4mpegpipe", "-i", "-"] + ["-pix_fmt", self._pixfmt_for_clip(clip)]
        return input_arguments, prop_args
        # fmt: on


@dataclass
class SupportsQP(VideoEncoder):
    settings: str | PathLike | None = None
    zones: Zone | list[Zone] | None = None
    qp_file: PathLike | bool | None = None
    qp_clip: src_file | vs.VideoNode | None = None
    add_props: bool | None = None
    sar: str | None = None
    quiet_merging: bool = True
    x265 = True

    def _get_qpfile(self, start_frame: int = 0) -> str:
        if not self.qp_file and not self.qp_clip:
            return ""

        if not isinstance(self.qp_file, bool) and self.qp_file is not None:
            return str(ensure_path_exists(self.qp_file, self).resolve())

        if self.qp_clip:
            if isinstance(self.qp_clip, src_file):
                self.qp_clip = self.qp_clip.src_cut
            return generate_qp_file(self.qp_clip, start_frame)

    def _init_settings(self, x265: bool):
        if not self.settings:
            s, p = file_or_default(f"{'x265' if x265 else 'x264'}_settings", sb265() if x265 else sb264())
            self.was_file = p
            self.settings = s
        else:
            s, p = file_or_default(self.settings, self.settings, True)
            self.was_file = p
            self.settings = s

        if self.add_props is None:
            self.add_props = not getattr(self, "was_file", False)

    def _update_settings(self, clip: vs.VideoNode, x265: bool):
        if self.was_file:
            self.settings = fill_props(self.settings, clip, x265, self.sar)

        self.settings = self.settings if isinstance(self.settings, list) else shlex.split(self.settings)

        if self.add_props:
            self.settings.extend(props_args(clip, x265, self.sar))

    @abstractmethod
    def _encode_clip(self, clip: vs.VideoNode, out: Path) -> Path: ...

    def encode(self, clip: vs.VideoNode, outfile: PathLike | None = None) -> VideoFile:
        if clip.format.bits_per_sample > (12 if self.x265 else 10):
            warn(f"This encoder does not support a bit depth over {(12 if self.x265 else 10)}.\nClip will be dithered to 10 bit.", self, 2)
            clip = finalize_clip(clip, 10)
        self._update_settings(clip, self.x265)
        out = make_output(
            Path(self.qp_clip.file).stem if isinstance(self.qp_clip, src_file) else "encoded",
            "265" if self.x265 else "264",
            "encoded" if isinstance(self.qp_clip, src_file) else "",
            outfile,
        )
        if not self.resumable:
            return VideoFile(self._encode_clip(clip, out, self._get_qpfile()))

        pattern = out.with_stem(out.stem + "_part_???")
        parts = sorted(pattern.parent.glob(pattern.name))
        info(f"Found {len(parts)} part{'s' if len(parts) != 1 else ''} for this encode")

        keyframes = list[int]()
        for i, p in enumerate(parts):
            try:
                info(f"Parsing keyframes for part {i}...")
                kf = parse_keyframes(p)[-1]
                if kf == 0:
                    del parts[-1]
                else:
                    keyframes.append(kf)
            except:
                del parts[-1]
        fout = out.with_stem(out.stem + f"_part_{len(parts):03.0f}")
        start_frame = sum(keyframes)
        info(f"Starting encode at frame {start_frame}")

        # TODO: Normalize and adjust existing zones to the new start frame

        clip = clip[start_frame:]
        self._encode_clip(clip, fout, self._get_qpfile(start_frame), start_frame)

        info("Remuxing and merging parts...")
        merge_parts(fout, out, keyframes, parts, self.quiet_merging)
        return VideoFile(out, source=self.qp_clip.file if isinstance(self.qp_clip, src_file) else None)
