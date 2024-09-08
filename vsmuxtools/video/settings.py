import os
import re
from typing import cast

from muxtools import PathLike, ensure_path, error, warn
from vstools import CustomValueError, vs

from .encoders.types import Zone

__all__ = ["settings_builder_x265", "settings_builder_x264", "sb", "sb265", "sb264"]


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
        zone = list(zone)
        zone[0] = zone[0] - start_frame
        zone[1] = zone[1] - start_frame
        if zone[1] < 0:
            continue
        if zone[0] < 0:
            zone[0] = 0
        zone = tuple(zone)
        newzones.append(zone)

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
            if x265 and zone[2].lower() not in ["q", "b"]:
                raise error(f"Zone '{zone}' is invalid for x265. Please only use b or q.")
            zones_settings += f"{zone[0]},{zone[1]},{zone[2]}={zone[3]}"
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
    settings += f" --deblock={deblock}"

    for k, v in kwargs.items():
        prefix = "--"
        if k.startswith("_"):
            prefix = "-"
            k = k[1:]
        settings += f" {prefix}{k.replace('_', '-')} {v}"

    settings += (" " + append.strip()) if append.strip() else ""
    return settings


sb = settings_builder_x265
sb265 = sb
sb264 = settings_builder_x264


def file_or_default(file: PathLike, default: str, no_warn: bool = False) -> tuple[str | list[str], bool]:
    if isinstance(file, list):
        return file, False
    if os.path.isfile(file):
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
