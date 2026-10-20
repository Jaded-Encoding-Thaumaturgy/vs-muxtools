"""Build static HDR and segment-aligned dynamic metadata arguments."""

from muxtools import error
from vstools import vs

from ..clip_metadata import HDR10Metadata, hdr10_args
from .helpers import DolbyVision, HDR10Plus


def hdr_args(
    clip: vs.VideoNode,
    existing_args: list[str],
    *,
    x265: bool,
    dolby_vision: DolbyVision | None = None,
    hdr10plus: HDR10Plus | None = None,
    hdr10: HDR10Metadata | bool = True,
    start_frame: int = 0,
) -> list[str]:
    end_frame = start_frame + clip.num_frames
    args = hdr10_args(clip, x265=x265, hdr10=hdr10, existing_args=existing_args)
    for helper, option in ((dolby_vision, "--dolby-vision-rpu"), (hdr10plus, "--dhdr10-info" if x265 else "--hdr10plus-json")):
        if helper is not None:
            if helper.frame_count != end_frame:
                raise error(f"Prepared metadata has {helper.frame_count} frames, but the output timeline has {end_frame}.", hdr_args)
            args.extend([option, str(helper.prepare(frames=(start_frame, end_frame)))])
    if dolby_vision is not None and x265:
        args.extend(["--dolby-vision-profile", str(dolby_vision.resolved_profile)])
    return args
