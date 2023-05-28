from vstools import vs
from os import PathLike
from dataclasses import dataclass
from abc import ABC, abstractmethod
from muxtools import get_executable, ensure_path_exists, VideoFile

from ..utils.src import generate_qp_file, src_file


@dataclass
class VideoEncoder(ABC):
    clip: vs.VideoNode
    resumable = False

    @abstractmethod
    def encode(self, clip: vs.VideoNode, outfile: PathLike | None = None) -> VideoFile:
        ...


@dataclass
class SupportsQP(VideoEncoder):
    qp_file: PathLike | bool | None = None
    qp_clip: src_file | vs.VideoNode | None = None

    def _get_qpfile(self) -> str:
        if not self.qp_file and not self.qp_clip:
            return ""

        if not isinstance(self.qp_file, bool) and self.qp_file is not None:
            return str(ensure_path_exists(self.qp_file, self).resolve())

        if self.qp_clip:
            if isinstance(self.qp_clip, src_file):
                self.qp_clip = self.qp_clip.src_cut
            return generate_qp_file(self.qp_clip)
