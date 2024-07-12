from typing import Union
from collections.abc import Callable
from vstools import vs, GenericVSFunction, get_video_format, depth

from .base import VideoEncoder
from .ffmpeg import ProRes
from .types import ProResProfile

from muxtools import VideoFile, PathLike, error, get_workdir
from muxtools.utils.dataclass import dataclass, allow_extra

__all__ = ["IntermediaryEncoder", "ProResIntermediary"]


@dataclass(config=allow_extra)
class IntermediaryEncoder(VideoEncoder):
    """
    Encoder that will create an intermediary first and then encode that intermediary to the target encoders.

    :param encoder:             The intermediary encoder. Might recommend prores or ffv1.

    :param target_encoders:     Target encoders to use. You can also pass a tuple with a function to call on the clips before running.
                                For example: (x265(), lambda clip: clip.nlm_cuda.NLMeans(h=2.0))

    :param indexer:             Here you can pass a custom indexing function ala FileInfo. Uses vsmuxtools.src otherwise.
    """

    encoder: VideoEncoder
    target_encoders: list[Union[VideoEncoder, tuple[VideoEncoder, GenericVSFunction]]]
    indexer: Callable[[str], vs.VideoNode] | None = None

    def encode(self, clip: vs.VideoNode, outfile: PathLike | None = None) -> list[VideoFile]:
        intermediary = self.encoder.encode(clip, get_workdir() / "intermediary")
        from vsmuxtools import src as src_index

        index_clip = self.indexer(str(intermediary.file)) if self.indexer else src_index(intermediary.file, force_lsmas=True)

        outputs = list[VideoFile]()

        for target in self.target_encoders:
            temp_clip = temp_clip = target[1](index_clip) if isinstance(target, tuple) else index_clip
            encoder = target[0] if isinstance(target, tuple) else target
            result = encoder.encode(temp_clip)
            outputs.append(result)

        return outputs


@dataclass(config=allow_extra)
class ProResIntermediary(VideoEncoder):
    """
    This encodes to prores first and will upscale chroma to 422 with point if needed and undo it before passing to other encoders.

    :param target_encoders:     Target encoders to use. You can also pass a tuple with a function to call on the clips before running.
                                For example: (x265(), lambda clip: clip.nlm_cuda.NLMeans(h=2.0))

    :param indexer:             Here you can pass a custom indexing function ala FileInfo. Uses vsmuxtools.src otherwise.

    :param profile:             The encoder profile. Basically Quality settings.
                                Chooses the Standard/Default profile for 422 and the '4444' profile for 444 clips if None.
    """

    target_encoders: list[VideoEncoder]
    indexer: Callable[[str], vs.VideoNode] | None = None
    profile: ProResProfile | int | None = None

    def encode(self, clip: vs.VideoNode, outfile: PathLike | None = None) -> list[VideoFile]:
        clipf = get_video_format(clip)
        try:
            from vskernels import Point
        except:
            raise error("You need to install vskernels for this", self)
        if clipf.subsampling_h != 0:
            clip = Point.resample(clip, format=clipf.replace(subsampling_h=0))

        encoder = IntermediaryEncoder(
            ProRes(self.profile),
            self.target_encoders
            if clipf.subsampling_h == 0
            else [(enc, lambda x: depth(Point.resample(x, clipf), 10)) for enc in self.target_encoders],
            self.indexer,
        )
        return encoder.encode(clip)
