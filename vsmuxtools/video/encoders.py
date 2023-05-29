import shlex
import subprocess
from vstools import vs
from pathlib import Path
from dataclasses import dataclass
from abc import ABC, abstractmethod
from muxtools import get_executable, ensure_path_exists, VideoFile, PathLike, make_output, info, warn

from .resumable import merge_parts, parse_keyframes
from ..utils.types import Zone
from ..utils.src import generate_qp_file, src_file
from .settings import file_or_default, fill_props, props_args, sb264, sb265


@dataclass
class VideoEncoder(ABC):
    settings: str | PathLike | None = None
    resumable = False

    @abstractmethod
    def encode(self, clip: vs.VideoNode, outfile: PathLike | None = None) -> VideoFile:
        ...

    def _update_progress(self, current_frame, total_frames):
        print(f"\rVapoursynth: {current_frame} / {total_frames} " f"({100 * current_frame // total_frames}%) || Encoder: ", end="")


@dataclass
class SupportsQP(VideoEncoder):
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

        self.settings = shlex.split(self.settings)

        if self.add_props:
            self.settings.extend(props_args(clip, x265, self.sar))

    @abstractmethod
    def _encode_clip(self, clip: vs.VideoNode, out: Path) -> Path:
        ...

    def encode(self, clip: vs.VideoNode, outfile: PathLike | None = None) -> VideoFile:
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
        info(f"Found {len(parts)} parts for this encode")

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

        # TODO: Adjust existing zones to the new start frame

        clip = clip[start_frame:]
        self._encode_clip(clip, fout, self._get_qpfile(start_frame))

        info("Merging parts...")
        merge_parts(fout, out, keyframes, parts, self.quiet_merging)
        return VideoFile(out, source=self.qp_clip.file if isinstance(self.qp_clip, src_file) else None)


@dataclass
class x264(SupportsQP):
    resumable: bool = True
    x265 = False

    def __post_init__(self):
        self.executable = get_executable("x264")
        self._init_settings(self.x265)

    def _encode_clip(self, clip: vs.VideoNode, out: Path, qpfile: str) -> Path:
        args = [self.executable, "-o", str(out.resolve())]
        if qpfile:
            args.extend(["--qpfile", qpfile])
        if self.settings:
            args.extend(self.settings if isinstance(self.settings, list) else shlex.split(self.settings))
        # --demuxer y4m -
        args.extend(["--demuxer", "y4m", "-"])

        process = subprocess.Popen(args, stdin=subprocess.PIPE)
        clip.output(process.stdin, y4m=True, progress_update=lambda x, y: self._update_progress(x, y))
        process.communicate()
        return out
