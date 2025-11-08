import re

from muxtools import warn
from muxtools.helpers.bsf import BSF_Matrix, BSF_Primaries, BSF_Transfer
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
    transfer = BSF_Transfer(Transfer.from_video(clip).value)
    matrix = BSF_Matrix(Matrix.from_video(clip).value)
    primaries = BSF_Primaries(Primaries.from_video(clip).value)

    str_props = KwargsT(
        depth=str(clip_format.bits_per_sample),
        range=color_range_strings[0] if color_range.is_full else color_range_strings[1],
        chromaloc=str(chromaloc.string if use_strings and chromaloc_string else chromaloc.value),
        transfer=str(transfer.value if not use_strings else transfer.name.lower()),
        colormatrix=str(matrix.value if not use_strings else matrix.name.lower()),
        primaries=str(primaries.value if not use_strings else primaries.name.lower()),
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
        sarnum = props["sarnum"]
        sarden = props["sarden"]
        if sarnum != "1" or sarden != "1":
            warn(f"Are you sure your SAR ({sarnum}:{sarden}) is correct?\nAre you perhaps working on an anamorphic source?", None, 2)
    settings = re.sub(r"{chromaloc(?::.)?}", props["chromaloc"], settings)
    settings = re.sub(r"{primaries(?::.)?}", props["primaries"], settings)
    settings = re.sub(r"{bits(?::.)?}", props["depth"], settings)
    settings = re.sub(r"{matrix(?::.)?}", props["colormatrix"], settings)
    settings = re.sub(r"{range(?::.)?}", props["range"], settings)
    settings = re.sub(r"{transfer(?::.)?}", props["transfer"], settings)
    settings = re.sub(r"{frames(?::.)?}", props["frames"], settings)
    settings = re.sub(r"{fps_num(?::.)?}", props["fps_num"], settings)
    settings = re.sub(r"{fps_den(?::.)?}", props["fps_den"], settings)
    settings = re.sub(r"{min_keyint(?::.)?}", props["min_keyint"], settings)
    settings = re.sub(r"{keyint(?::.)?}", props["keyint"], settings)
    settings = re.sub(r"{sarnum(?::.)?}", sarnum, settings)
    settings = re.sub(r"{sarden(?::.)?}", sarden, settings)
    settings = re.sub(r"{min_luma(?::.)?}", props["min_luma"], settings)
    settings = re.sub(r"{max_luma(?::.)?}", props["max_luma"], settings)
    settings = re.sub(r"{lookahead(?::.)?}", props["lookahead"], settings)
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
        "--input-depth", props["depth"],
        "--output-depth", props["depth"],
        "--transfer", props["transfer"],
        "--chromaloc", props["chromaloc"],
        "--colormatrix", props["colormatrix"],
        "--range", props["range"],
        "--colorprim", props["primaries"],
        "--sar", f"{sarnum}:{sarden}",
        "--frames", props["frames"]
    ])
    if x265:
        args.extend([
            "--min-luma", props["min_luma"],
            "--max-luma", props["max_luma"]
        ])
    return args
    # fmt: on
