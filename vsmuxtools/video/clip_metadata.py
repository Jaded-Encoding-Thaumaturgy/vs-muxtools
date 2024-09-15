import re

from muxtools import warn
from vstools import ChromaLocation, ColorRange, Matrix, Primaries, Transfer, vs, get_video_format, KwargsT

__all__ = ["props_dict", "fill_props", "props_args", "X264_RANGES", "SVT_AV1_RANGES"]

SVT_AV1_RANGES = ("full", "studio")
X264_RANGES = ("pc", "tv")


def props_dict(
    clip: vs.VideoNode, use_strings: bool, color_range_strings: tuple[str, str] = ("full", "limited"), chromaloc_string: bool = True
) -> dict[str, str]:
    color_range = ColorRange.from_video(clip)
    clip_format = get_video_format(clip)
    props = clip.get_frame(0).props
    chromaloc = ChromaLocation.from_video(clip)
    transfer = Transfer.from_video(clip)
    matrix = Matrix.from_video(clip)
    primaries = Primaries.from_video(clip)

    str_props = KwargsT(
        depth=str(clip_format.bits_per_sample),
        range=color_range_strings[0] if color_range.is_full else color_range_strings[1],
        chromaloc=str(chromaloc.string if use_strings and chromaloc_string else chromaloc.value),
        transfer=str(transfer.value if not use_strings else transfer.string),
        colormatrix=str(matrix.value if not use_strings else matrix.string),
        primaries=str(primaries.value if not use_strings else primaries.string),
        sarnum=str(props.get("_SARNum", 1)),
        sarden=str(props.get("_SARDen", 1)),
        keyint=str(round(clip.fps) * 10),
        min_keyint=str(round(clip.fps)),
        frames=str(clip.num_frames),
        fps_num=str(clip.fps_num),
        fps_den=str(clip.fps_den),
        min_luma=str(16 << (clip_format.bits_per_sample - 8) if color_range.is_limited else 0),
        max_luma=str(235 << (clip_format.bits_per_sample - 8) if color_range.is_limited else (1 << clip_format.bits_per_sample) - 1),
        lookahead=str(min(clip.fps_num * 5, 250)),
    )
    return str_props


def fill_props(settings: str, clip: vs.VideoNode, x265: bool, sar: str | None = None) -> str:
    props = props_dict(clip, False) if x265 else props_dict(clip, True, X264_RANGES, False)
    if sar is not None:
        if not isinstance(sar, str):
            sar = str(sar)
        sarnum = sar if ":" not in sar else sar.split(":")[0]
        sarden = sar if ":" not in sar else sar.split(":")[1]
    else:
        sarnum = props.get("sarnum")
        sarden = props.get("sarden")
        if sarnum != "1" or sarden != "1":
            warn(f"Are you sure your SAR ({sarnum}:{sarden}) is correct?\nAre you perhaps working on an anamorphic source?", None, 2)
    settings = re.sub(r"{chromaloc(?::.)?}", props.get("chromaloc"), settings)
    settings = re.sub(r"{primaries(?::.)?}", props.get("primaries"), settings)
    settings = re.sub(r"{bits(?::.)?}", props.get("depth"), settings)
    settings = re.sub(r"{matrix(?::.)?}", props.get("colormatrix"), settings)
    settings = re.sub(r"{range(?::.)?}", props.get("range"), settings)
    settings = re.sub(r"{transfer(?::.)?}", props.get("transfer"), settings)
    settings = re.sub(r"{frames(?::.)?}", props.get("frames"), settings)
    settings = re.sub(r"{fps_num(?::.)?}", props.get("fps_num"), settings)
    settings = re.sub(r"{fps_den(?::.)?}", props.get("fps_den"), settings)
    settings = re.sub(r"{min_keyint(?::.)?}", props.get("min_keyint"), settings)
    settings = re.sub(r"{keyint(?::.)?}", props.get("keyint"), settings)
    settings = re.sub(r"{sarnum(?::.)?}", sarnum, settings)
    settings = re.sub(r"{sarden(?::.)?}", sarden, settings)
    settings = re.sub(r"{min_luma(?::.)?}", props.get("min_luma"), settings)
    settings = re.sub(r"{max_luma(?::.)?}", props.get("max_luma"), settings)
    settings = re.sub(r"{lookahead(?::.)?}", props.get("lookahead"), settings)
    return settings


def props_args(clip: vs.VideoNode, x265: bool, sar: str | None = None) -> list[str]:
    args: list[str] = []
    props = props_dict(clip, False) if x265 else props_dict(clip, True, X264_RANGES, False)
    if sar is not None:
        if not isinstance(sar, str):
            sar = str(sar)
        sarnum = sar if ":" not in sar else sar.split(":")[0]
        sarden = sar if ":" not in sar else sar.split(":")[1]
    else:
        sarnum = props.get("sarnum")
        sarden = props.get("sarden")
        if sarnum != "1" or sarden != "1":
            warn(f"Are you sure your SAR ({sarnum}:{sarden}) is correct?\nAre you perhaps working on an anamorphic source?", None, 2)

    # fmt: off
    args.extend([
        "--input-depth", props.get("depth"),
        "--output-depth", props.get("depth"),
        "--transfer", props.get("transfer"),
        "--chromaloc", props.get("chromaloc"),
        "--colormatrix", props.get("colormatrix"),
        "--range", props.get("range"),
        "--colorprim", props.get("primaries"),
        "--sar", f"{sarnum}:{sarden}"
    ])
    if x265:
        args.extend([
            "--min-luma", props.get("min_luma"),
            "--max-luma", props.get("max_luma")
        ])
    return args
    # fmt: on
