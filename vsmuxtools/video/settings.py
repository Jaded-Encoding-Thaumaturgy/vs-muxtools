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
    "settings_builder_5fish_svt_av1_psy",
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


def settings_builder_5fish_svt_av1_psy(
    preset: int = 2,
    crf: float = 20.00,
    lineart_psy_bias: int = 3,
    texture_psy_bias: int = 3,
    progress: int | None = 2,
    **kwargs,
) -> dict[str, Any]:
    """
    This is a settings_builder for 5fish/SVT-AV1-PSY.
    These parameters correspond to mid March 2026 version of the encoder.

    Repository: https://github.com/5fish/svt-av1-psy .
    Windows build: https://github.com/Akatmks/svt-av1-psy-quality/releases .
    Linux build: `Build/linux/build.sh --native --static --release --enable-lto --enable-pgo` with clang highly recommended over gcc.

    For high fidelity encodes, start at `--preset 0 --crf 12.00`.
    You should regrain and do every other filtering just as you would for a high fidelity x265 encode. This will work fine.
    For even better efficiency, you can offload high frequency part of the regraining noise onto AV1's film grain layer by writing a photon noise table.

    For middle quality (for example, ~ 6 Mbps) encodes, start at `--preset 2 --crf 20.00`.
    For most cases, you should be able to rely on writing a good photon noise table instead of regraining to achieve best detail retention for the given filesize. The builtin photon noise table of `SVTAV1` can deal with some basic situations as well. Otherwise you can do all other filtering as normal and make sure they are as protective as they can.

    For mini encodes, start at `--preset 2 --crf 28.00`.
    You want to remove temporal noise as much as you can while keeping static texture intact. Do not regrain for mini encode. Other than this, you want to still make every process including denoise and deband protective.

    If it's a source with very heavy artistic temporal noise and you would not or could not remove the temporal noise, but you still want to get it to a very small filesize (< 3 Mbps), you should use SVT-AV1-Essential instead, as SVT-AV1-Essential throws away information more aggressively and can achieve a good looking result in noisy source even at very small filesize.

    For both middle quality and mini encodes, `--preset 2` is preferred over slower `--preset 0`. Specifically this is because, internally, different `--preset` uses different methods to search for the best encoding option for each block. Without a high fidelity specific parameter (`--satd-bias`) that's internally enabled at `--crf [<= 16.00]`, it is better to use the `--preset 2`'s search strategy rather than `--preset 0`'s search strategy.

    After setting up `--preset` and `--crf`, you should set a good `--lineart-psy-bias` and `--texture-psy-bias` value depending on how much effort you want to spend on them.

    `--lineart-psy-bias 3` is generally good for all sources, especially sources without weak lineart and easier to handle.
    `--lineart-psy-bias 4` puts a little bit more focus on weak lineart retention than `--lineart-psy-bias 3`.
    `--lineart-psy-bias 5` and above is optimised for weak lineart retention. Some features here trade overall efficiency for better weak lineart retention, and some features here are tuned very aggressively and may cause issues in texture heavy sources.

    `--texture-psy-bias 2` is fine to use on sources with little texture.
    `--texture-psy-bias 3` puts a little bit of focus on texture, and can be used on sources with occasional texture.
    `--texture-psy-bias 4` is suitable for sources with detailed texture. At this level, it starts to harm especially weak lineart in clean sources a little bit, but should still generally be fine for most sources.
    `--texture-psy-bias 5` and above is suitabled for encodes where texture retention is a great priority, or when the source is very texture heavy or covered by a layer of static noise.

    For better explanations of parameters, and to adjust the encoder beyond the two main `-psy-bias`s, check the `Docs/Parameters.md` file in encoder's GitHub.
    For how to set the parameters for your source, as well as how to generate your own photon noise table, check the guides section in the AV1 weeb server, specifically “High effort high quality AV1 encode note collection”.

    To use this settings_builder,
    ```py
    settings = settings_builder_5fish_svt_av1_psy(...)
    mini = SVTAV1(**settings, sd_clip=src).encode(final)
    ```
    """
    args = dict[str, Any]()
    args["_settings_builder_id"] = r"SVT-AV1-PSY \[5fish"

    for k in inspect.getfullargspec(settings_builder_5fish_svt_av1_psy).args:
        if locals()[k] is not None:
            args[k] = locals()[k]

    return args | kwargs


def settings_builder_svt_av1_essential(
    speed: str | None = "slower",
    quality: str | None = "medium",
    preset: int | None = None,
    crf: int | None = None,
    luminance_qp_bias: int | None = 20,
    scm: int | None = 0,
    progress: int | None = 3,
    **kwargs,
) -> dict[str, Any]:
    """
    This is a settings_builder for SVT-AV1-Essential.
    These parameters correspond to v3.1.2-Essential.

    Repository: https://github.com/nekotrix/SVT-AV1-Essential .
    Windows build: https://github.com/Akatmks/svt-av1-psy-quality/releases .
    Linux build: apply patches if available, and build with `Build/linux/build.sh --native --static --release --enable-lto --enable-pgo` with clang highly recommended over gcc.

    SVT-AV1-Essential is better for mini encodes and is optimised to give a good looking result given any source, with or without filtering.
    You should not regrain before sending to SVT-AV1.

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
