import re
from typing import Annotated, Any, Self

from muxtools import error, warn
from muxtools.helpers.bsf import BSF_Matrix, BSF_Primaries, BSF_Transfer
from jetpytools import KwargsT
from pydantic import BaseModel, ConfigDict, Field, model_validator
from vstools import ChromaLocation, ColorRange, Matrix, Primaries, Transfer, vs, get_video_format

__all__ = ["props_dict", "fill_props", "props_args", "X264_RANGES", "SVT_AV1_RANGES", "HDR10Metadata"]

SVT_AV1_RANGES = ("full", "studio")
X264_RANGES = ("pc", "tv")


_Coordinate = Annotated[float, Field(strict=True, ge=0, le=1)]
_XY = tuple[_Coordinate, _Coordinate]
_Primaries = tuple[_XY, _XY, _XY]


class HDR10Metadata(BaseModel):
    """Static HDR10 mastering-display and content-light metadata.

    Every value is optional, but fields belonging to one metadata group must
    be supplied together.  Coordinates are stored as normalized xy values and
    luminance values are stored in nits.

    :param primaries: RGB primaries in ``(x, y)`` order, as R, G, B.
    :param white_point: Display white point as a normalized ``(x, y)`` pair.
    :param min_luminance: Minimum mastering-display luminance in nits.
    :param max_luminance: Maximum mastering-display luminance in nits.
    :param max_cll: Maximum content light level in nits.
    :param max_fall: Maximum frame-average light level in nits.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    primaries: _Primaries | None = None
    white_point: _XY | None = None
    min_luminance: float | None = Field(default=None, ge=0, strict=True)
    max_luminance: float | None = Field(default=None, gt=0, strict=True)
    max_cll: int | None = Field(default=None, ge=0, strict=True)
    max_fall: int | None = Field(default=None, ge=0, strict=True)

    @model_validator(mode="after")
    def _validate_groups(self) -> Self:
        mastering = (self.primaries, self.white_point, self.min_luminance, self.max_luminance)
        if any(value is not None for value in mastering) and not all(value is not None for value in mastering):
            raise ValueError("primaries, white_point, min_luminance and max_luminance must be supplied together")
        if self.min_luminance is not None and self.max_luminance is not None and self.min_luminance > self.max_luminance:
            raise ValueError("luminance values must satisfy 0 <= min_luminance <= max_luminance")

        if (self.max_cll is None) != (self.max_fall is None):
            raise ValueError("max_cll and max_fall must be supplied together")
        if self.max_cll is not None and self.max_fall is not None and self.max_fall > self.max_cll:
            raise ValueError("max_fall cannot exceed max_cll")
        return self

    @classmethod
    def from_clip(cls, clip: vs.VideoNode) -> "HDR10Metadata":
        """Read static HDR10 metadata from the first frame of ``clip``.

        Incomplete or invalid automatic groups are omitted.  Frame properties
        are read as-is; no mastering values are inferred from colour signals.

        :param clip: Video clip whose first frame contains the metadata.
        :return: Metadata groups that are complete and valid on frame zero.
        """

        props = clip.get_frame(0).props
        metadata: dict[str, object] = {}
        primary_x: Any = props.get("MasteringDisplayPrimariesX")
        primary_y: Any = props.get("MasteringDisplayPrimariesY")
        try:
            mastering = cls.model_validate(
                {
                    "primaries": tuple(zip(primary_x, primary_y, strict=True)),
                    "white_point": (props.get("MasteringDisplayWhitePointX"), props.get("MasteringDisplayWhitePointY")),
                    "min_luminance": props.get("MasteringDisplayMinLuminance"),
                    "max_luminance": props.get("MasteringDisplayMaxLuminance"),
                }
            )
        except (TypeError, ValueError):
            pass
        else:
            metadata.update(mastering.model_dump(exclude_none=True))

        try:
            levels = cls.model_validate(
                {
                    "max_cll": props.get("ContentLightLevelMax"),
                    "max_fall": props.get("ContentLightLevelAverage"),
                }
            )
        except (TypeError, ValueError):
            pass
        else:
            metadata.update(levels.model_dump(exclude_none=True))

        return cls.model_validate(metadata)


def _has_arg(args: list[str], options: tuple[str, ...]) -> bool:
    return any(arg == option or arg.startswith(f"{option}=") for arg in args for option in options)


def _master_display_text(metadata: HDR10Metadata, x265: bool) -> str | None:
    if metadata.primaries is None or metadata.white_point is None or metadata.min_luminance is None or metadata.max_luminance is None:
        return None
    values = (metadata.primaries[1], metadata.primaries[2], metadata.primaries[0], metadata.white_point)
    if x265:
        points = "".join(f"{name}({round(point[0] * 50000)},{round(point[1] * 50000)})" for name, point in zip(("G", "B", "R"), values[:3]))
        white = f"WP({round(values[3][0] * 50000)},{round(values[3][1] * 50000)})"
        luminance = f"L({round(metadata.max_luminance * 10000)},{round(metadata.min_luminance * 10000)})"
    else:
        points = "".join(f"{name}({point[0]},{point[1]})" for name, point in zip(("G", "B", "R"), values[:3]))
        white = f"WP({values[3][0]},{values[3][1]})"
        luminance = f"L({metadata.max_luminance},{metadata.min_luminance})"
    return points + white + luminance


def _light_level_text(metadata: HDR10Metadata) -> str | None:
    if metadata.max_cll is None or metadata.max_fall is None:
        return None
    return f"{metadata.max_cll},{metadata.max_fall}"


def hdr10_args(
    clip: vs.VideoNode,
    *,
    x265: bool,
    hdr10: HDR10Metadata | bool = True,
    existing_args: list[str] | None = None,
) -> list[str]:
    """Build additional static HDR10 encoder arguments, respecting explicit settings.

    :param clip: Output clip being encoded.
    :param x265: Select x265 syntax when true, or SVT-AV1 syntax otherwise.
    :param hdr10: Automatic metadata, an explicit metadata override, or false to disable it.
    :param existing_args: Existing expanded CLI arguments to inspect for explicit settings.
    :return: Missing HDR10 arguments to append to the encoder command.
    """

    existing_args = existing_args or []
    args: list[str] = []
    if hdr10 is False:
        return args
    if not isinstance(hdr10, (bool, HDR10Metadata)):
        raise error("hdr10 must be a bool or HDR10Metadata", hdr10_args)

    metadata = hdr10 if isinstance(hdr10, HDR10Metadata) else HDR10Metadata.from_clip(clip)

    display_option = "--master-display" if x265 else "--mastering-display"
    display_value = _master_display_text(metadata, x265)
    if display_value is not None and not _has_arg(existing_args, (display_option,)):
        args.extend([display_option, display_value])

    light_option = "--max-cll" if x265 else "--content-light"
    light_value = _light_level_text(metadata)
    if light_value is not None and not _has_arg(existing_args, (light_option,)):
        args.extend([light_option, light_value])

    return args


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
            warn(f"Are you sure your SAR ({sarnum}:{sarden}) is correct?\nAre you perhaps working on an anamorphic source?", None)
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
            warn(f"Are you sure your SAR ({sarnum}:{sarden}) is correct?\nAre you perhaps working on an anamorphic source?", None)

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
