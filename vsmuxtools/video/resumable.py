from pathlib import Path
import re
import subprocess
from muxtools import ensure_path_exists, PathLike, get_executable, run_commandline, error, info


def parse_keyframes(file: PathLike) -> list[int]:
    file = ensure_path_exists(file, parse_keyframes)
    frames = list[int]()
    ffprobe = get_executable("ffprobe")
    args = [ffprobe, "-select_streams", "v", "-show_frames", "-show_entries", "frame=pict_type", str(file)]
    out = subprocess.run(args, capture_output=True, text=True)
    current = 0
    for line in out.stdout.splitlines():
        line = line.strip()
        if line.startswith("pict_type"):
            if line.split("=")[1] == "I":
                frames.append(current)
            current += 1
    return frames


def merge_parts(last: Path, original_out: Path, keyframes: list[int], parts: list[Path], quiet: bool = True):
    # This function is partially stolen from vardautomation but with less weird abstraction
    mkvmerge = get_executable("mkvmerge")
    mkvextract = get_executable("mkvextract")

    _to_delete = set[Path]()
    mkv_parts = list[Path]()
    # Remux and split existing parts
    for kf, part in zip(keyframes, parts):
        as_mkv = part.with_suffix(".mkv").resolve()
        args = [mkvmerge, "-o", str(as_mkv), "--split", f"frames:{kf}", str(part.resolve())]
        if run_commandline(args, quiet) > 1:
            raise error("Failed to remux existing part", merge_parts)
        # mkvmerge will spit out parts with this kind of naming and there will only be two
        p_mkv001 = as_mkv.with_stem(as_mkv.stem + "-001")
        p_mkv002 = as_mkv.with_stem(as_mkv.stem + "-002")
        # we only need the first one ofc
        mkv_parts.append(p_mkv001)
        _to_delete.update([p_mkv001, p_mkv002])
    _to_delete.update(parts)

    if len(mkv_parts) < 1:
        info("Encode finished successfully without requiring other parts")
        for f in _to_delete:
            f.unlink(True)
        last.rename(original_out)
        return

    # Remux the last encoded part
    last_mkv = last.with_suffix(".mkv").resolve()
    args = [mkvmerge, "-o", str(last_mkv), str(last.resolve())]
    if run_commandline(args, quiet) > 1:
        raise error("Failed to remux last part", merge_parts)
    mkv_parts.append(last_mkv)
    _to_delete.update([last_mkv, last])

    out_mkv = original_out.with_suffix(".mkv").resolve()

    args = [mkvmerge, "-o", str(out_mkv)]
    first = True
    for part in mkv_parts:
        if not first:
            args.append("+")
        args.append(str(part.resolve()))
        first = False

    if run_commandline(args, quiet) > 1:
        raise error("Failed to remux last part", merge_parts)

    info("Extracting merged part...")
    args = [mkvextract, str(out_mkv), "tracks", f"0:{str(original_out.resolve())}"]
    if run_commandline(args, quiet) > 1:
        raise error("Failed to extract merged track!", merge_parts)

    _to_delete.add(out_mkv)

    for f in _to_delete:
        f.unlink(True)
