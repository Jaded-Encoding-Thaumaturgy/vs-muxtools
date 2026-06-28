import os
import re
from typing import cast, Any
import inspect

from muxtools import PathLike, ensure_path, error, warn
from jetpytools import CustomValueError
from vstools import vs

from .encoders.types import Zone

__all__ = [
    "settings_builder_x265",
    "settings_builder_x264",
    "sb",
    "sb265",
    "sb264",
    "settings_builder_5fish_svt_av1_high_quality",
    "settings_builder_5fish_svt_av1_mini",
    "settings_builder_5fish_svt_av1_mini_high_dlf",
    "settings_builder_svt_av1_essential",
]


def is_full_zone(zone: Zone) -> bool:
    if isinstance(zone[2], str):
        if len(zone) < 4:
            raise error(f"Zone '{zone}' is invalid.")
        return True
    else:
        return False


def norm_zones(clip_or_max_frames: vs.VideoNode | int, zones: Zone | list[Zone] | None) -> list[Zone]:
    """
    Normalize zones to be within the clip's range.

    :param clip_or_max_frames:      The clip or a max frame count to normalize to.
    :param zones:                   The zones to normalize.

    :return:                        The normalized zones.
    """

    if not zones:
        return []

    max_frames = clip_or_max_frames if isinstance(clip_or_max_frames, int) else clip_or_max_frames.num_frames

    if not isinstance(zones, list):
        zones = [zones]

    newzones = list[Zone]()

    for zone in zones:
        start, end, *params = zone

        if start is None:
            start = 0
        elif isinstance(start, int) and start < 0:
            start = max_frames - abs(start)

        if end is None:
            end = max_frames - 1
        elif isinstance(end, int) and end < 0:
            end = max_frames - abs(end)

        if start > end:
            raise CustomValueError(f"Zone '{zone}' start frame is after end frame!", norm_zones, f"{start} > {end}")

        newzones.append(cast(Zone, (start, min(end, max_frames - 1), *params)))  # type:ignore[type-var]

    return newzones


def shift_zones(zones: Zone | list[Zone] | None, start_frame: int = 0) -> list[Zone] | None:
    if not zones:
        return None
    if not isinstance(zones, list):
        zones = [zones]

    newzones = list[Zone]()

    for zone in zones:
        assert zone[0] is not None and zone[1] is not None
        start = zone[0] - start_frame
        end = zone[1] - start_frame
        if end < 0:
            continue
        if start < 0:
            start = 0

        new_zone = list(zone)
        new_zone[0] = start
        new_zone[1] = end
        newzones.append(tuple(new_zone))  # type: ignore

    return newzones


def zones_to_args(zones: Zone | list[Zone] | None, x265: bool) -> list[str]:
    args: list[str] = []
    if not zones:
        return args
    if not isinstance(zones, list):
        zones = [zones]
    zones_settings: str = ""
    for i, zone in enumerate(zones):
        if is_full_zone(zone):
            if x265 and str(zone[2]).lower() not in ["q", "b"]:
                raise error(f"Zone '{zone}' is invalid for x265. Please only use b or q.")
            zones_settings += f"{zone[0]},{zone[1]},{zone[2]}={zone[3]}"  # type: ignore
        else:
            zones_settings += f"{zone[0]},{zone[1]},b={zone[2]}"
        if i != len(zones) - 1:
            zones_settings += "/"
    args.extend(["--zones", zones_settings])
    return args


def settings_builder_x265(
    preset: str | int = "slower",
    crf: float = 14.0,
    qcomp: float = 0.75,
    psy_rd: float = 2.0,
    psy_rdoq: float = 2.0,
    aq_strength: float = 0.75,
    aq_mode: int = 3,
    rd: int = 4,
    rect: bool = True,
    amp: bool = False,
    chroma_qpoffsets: int = -2,
    tu_intra_depth: int = 2,
    tu_inter_depth: int = 2,
    rskip: bool | int = 0,
    tskip: bool = False,
    ref: int = 4,
    bframes: int = 16,
    cutree: bool = False,
    rc_lookahead: int = 60,
    subme: int = 5,
    me: int = 3,
    b_intra: bool = True,
    weightb: bool = True,
    deblock: list[int] | str = [-2, -2],
    append: str = "",
    **kwargs,
) -> str:
    # Simple insert values
    settings = f" --preset {preset} --crf {crf} --bframes {bframes} --ref {ref} --rc-lookahead {rc_lookahead} --subme {subme} --me {me}"
    settings += f" --aq-mode {aq_mode} --aq-strength {aq_strength} --qcomp {qcomp} --cbqpoffs {chroma_qpoffsets} --crqpoffs {chroma_qpoffsets}"
    settings += f" --rd {rd} --psy-rd {psy_rd} --psy-rdoq {psy_rdoq} --tu-intra-depth {tu_intra_depth} --tu-inter-depth {tu_inter_depth}"

    # Less simple
    settings += f" --{'rect' if rect else 'no-rect'} --{'amp' if amp else 'no-amp'} --{'tskip' if tskip else 'no-tskip'}"
    settings += f" --{'b-intra' if b_intra else 'no-b-intra'} --{'weightb' if weightb else 'no-weightb'} --{'cutree' if cutree else 'no-cutree'}"
    settings += f" --rskip {int(rskip) if isinstance(rskip, bool) else rskip}"

    if isinstance(deblock, list):
        deblock = f"{str(deblock[0])}:{str(deblock[1])}"
    settings += f" --deblock={deblock}"

    # Don't need to change these lol
    settings += " --no-sao --no-sao-non-deblock --no-strong-intra-smoothing --no-open-gop"

    for k, v in kwargs.items():
        prefix = "--"
        if k.startswith("_"):
            prefix = "-"
            k = k[1:]
        settings += f" {prefix}{k.replace('_', '-')} {v}"

    settings += (" " + append.strip()) if append.strip() else ""
    return settings


def settings_builder_x264(
    preset: str = "placebo",
    crf: float = 13,
    qcomp: float = 0.7,
    psy_rd: float = 1.0,
    psy_trellis: float = 0.0,
    trellis: int | None = None,
    aq_strength: float = 0.8,
    aq_mode: int = 3,
    ref: int = 16,
    bframes: int = 16,
    mbtree: bool = False,
    rc_lookahead: int = 250,
    me: str = "umh",
    subme: int = 11,
    threads: int = 6,
    merange: int = 32,
    deblock: list[int] | str = [-1, -1],
    dct_decimate: bool = False,
    append: str = "",
    **kwargs,
) -> str:
    # Simple insert values
    settings = f" --preset {preset} --crf {crf} --bframes {bframes} --ref {ref} --rc-lookahead {rc_lookahead} --me {me} --merange {merange}"
    settings += f" --aq-mode {aq_mode} --aq-strength {aq_strength} --qcomp {qcomp}"
    settings += f" --psy-rd {psy_rd}:{psy_trellis} --subme {subme} --threads {threads}"
    if trellis is not None:
        settings += f" --trellis {trellis}"

    # Less simple
    settings += f" {'--no-mbtree' if not mbtree else ''} {'--no-dct-decimate' if not dct_decimate else ''}"

    if isinstance(deblock, list):
        deblock = f"{str(deblock[0])}:{str(deblock[1])}"
    settings += f" --deblock {deblock}"

    for k, v in kwargs.items():
        prefix = "--"
        if k.startswith("_"):
            prefix = "-"
            k = k[1:]
        settings += f" {prefix}{k.replace('_', '-')} {v}"

    settings += (" " + append.strip()) if append.strip() else ""
    return settings


def settings_builder_5fish_svt_av1_high_quality(
    preset: int = 0,
    crf: float = 13.00,
    lineart_psy_bias: int = 5,
    texture_psy_bias: int = 4,
    satd_bias: float | None = 0.50,
    progress: int | None = 2,
    **kwargs,
) -> dict[str, Any]:
    """
    This is a settings_builder for 5fish/SVT-AV1.
    These parameters correspond to early July 2026 version of the encoder.

    Source Repository & Builds: https://github.com/5fish/svt-av1 .

    This settings_builder uses `--preset 0`. If it is too slow, you can switch to `--preset 2` without losing much quality.

    If you want to adjust the parameters for your source, check the Usage section in `README.md` in encoder's GitHub repository.

    To use this settings_builder,
    ```py
    settings = settings_builder_5fish_svt_av1_high_quality()
    mini = SVTAV1(**settings, sd_clip=src).encode(final)
    ```
    """
    args = dict[str, Any]()
    args["_settings_builder_id"] = r"SVT-AV1 \[5fish"

    for k in inspect.getfullargspec(settings_builder_5fish_svt_av1_high_quality).args:
        if locals()[k] is not None:
            args[k] = locals()[k]

    return args | kwargs

def settings_builder_5fish_svt_av1_mini(
    preset: int = 2,
    crf: float = 24.00,
    lineart_psy_bias: int = 3,
    texture_psy_bias: int = 3,
    progress: int | None = 2,
    **kwargs,
) -> dict[str, Any]:
    """
    This is a settings_builder for 5fish/SVT-AV1.
    These parameters correspond to early July 2026 version of the encoder.

    Source Repository & Builds: https://github.com/5fish/svt-av1 .

    Compared to the `settings_builder_5fish_svt_av1_mini_high_dlf`, this version works best with clean sources.
    Ideally you want to remove temporal noise as much as you can without damaging texture before sending to the encoder.

    If you want to adjust the parameters for your source, check the Usage section in `README.md` in encoder's GitHub repository.

    To use this settings_builder,
    ```py
    settings = settings_builder_5fish_svt_av1_mini()
    mini = SVTAV1(**settings, sd_clip=src).encode(final)
    ```
    """
    args = dict[str, Any]()
    args["_settings_builder_id"] = r"SVT-AV1 \[5fish"

    for k in inspect.getfullargspec(settings_builder_5fish_svt_av1_mini).args:
        if locals()[k] is not None:
            args[k] = locals()[k]

    return args | kwargs

def settings_builder_5fish_svt_av1_mini_high_dlf(
    preset: int = 2,
    crf: float = 26.00,
    lineart_psy_bias: int = 5,
    texture_psy_bias: int = 4,
    dlf_bias_max_dlf: str | None = "24,4",
    dlf_bias_min_dlf: str | None = "16,0",
    dlf_sharpness: int | None = 7,
    texture_cdef_bias_max_cdef: str | None = "0,0,0,0",
    progress: int | None = 2,
    **kwargs,
) -> dict[str, Any]:
    """
    This is a settings_builder for 5fish/SVT-AV1.
    These parameters correspond to early July 2026 version of the encoder.

    Source Repository & Builds: https://github.com/5fish/svt-av1 .

    Compared to the `settings_builder_5fish_svt_av1_mini`, this high DLF version is suitable for noisy or even regrained sources.

    If you want to adjust the parameters for your source, check the Usage section in `README.md` in encoder's GitHub repository.

    To use this settings_builder,
    ```py
    settings = settings_builder_5fish_svt_av1_mini_high_dlf()
    mini = SVTAV1(**settings, sd_clip=src).encode(final)
    ```
    """
    args = dict[str, Any]()
    args["_settings_builder_id"] = r"SVT-AV1 \[5fish"

    for k in inspect.getfullargspec(settings_builder_5fish_svt_av1_mini_high_dlf).args:
        if locals()[k] is not None:
            args[k] = locals()[k]

    return args | kwargs


def settings_builder_svt_av1_essential(
    speed: str | None = "slower",
    quality: str | None = "medium",
    preset: int | None = None,
    crf: int | None = None,
    scm: int | None = 0,
    progress: int | None = 3,
    **kwargs,
) -> dict[str, Any]:
    """
    This is a settings_builder for SVT-AV1-Essential.
    These parameters correspond to v4.0.1-Essential.

    Repository: https://github.com/nekotrix/SVT-AV1-Essential .
    Windows build: https://github.com/Akatmks/svt-av1-psy-quality/releases .
    Linux build: apply patches if available, and build with `Build/linux/build.sh --native --static --release --enable-lto --enable-pgo` with clang highly recommended over gcc.

    For higer quality mini and non mini encodes, check out `settings_builder_5fish_svt_av1_psy`.

    For better explanations of parameters, check the `Docs/Parameters.md` file in encoder's GitHub.

    To use this settings_builder,
    ```py
    settings = settings_builder_svt_av1_essential(...)
    mini = SVTAV1(**settings).encode(final)
    ```

    :param speed:           Adjust the speed.
                            `slower` (`--preset 2`) is the recommended starting point. `slow` (`--preset 4`) is faster.
    :param quality:         Adjust the quality.
                            `medium` (`--crf 30`) is the recommended starting point. `high` (`--crf 25`) is higher, and `low` (`--crf 35`), or `lower` (`--crf 40`) is lower.
    """
    args = dict[str, Any]()
    args["_settings_builder_id"] = "SVT-AV1-Essential"

    for k in inspect.getfullargspec(settings_builder_svt_av1_essential).args:
        if locals()[k] is not None:
            args[k] = locals()[k]

    args = args | kwargs

    if "speed" in args and "preset" in args:
        del args["speed"]
    if "quality" in args and "crf" in args:
        del args["quality"]

    if "speed" not in args and "preset" not in args:
        raise error("You must specify either speed or preset", settings_builder_svt_av1_essential)
    if "quality" not in args and "crf" not in args:
        raise error("You must specify either quality or crf", settings_builder_svt_av1_essential)

    return args


sb = settings_builder_x265
sb265 = sb
sb264 = settings_builder_x264


def file_or_default(file: PathLike | list[str], default: str, no_warn: bool = False) -> tuple[str | list[str], bool]:
    if isinstance(file, list):
        return file, False
    if file is not None and os.path.isfile(file):
        file = ensure_path(file, None)
        if file.exists():
            with open(file, "r") as r:
                settings = str(r.read())
                settings = settings.replace("\n", " ")
                settings = re.sub(r"(?:-o|--output) {clip.+?}", "", settings, flags=re.I).strip()
                return settings, True

    if not no_warn:
        warn("Settings file wasn't found. Using default.", None, 3)
    return default, False
