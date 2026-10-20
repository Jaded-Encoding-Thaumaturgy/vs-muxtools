"""Small decoded side-data checks shared by the encode tests."""

import json
from fractions import Fraction
from pathlib import Path
from typing import Any

from muxtools import get_executable, ParsedFile
from muxtools.utils.env import communicate_stdout
from vsmuxtools import DolbyVision, HDR10Plus


def probe(path: Path, *, frames: bool = False) -> dict[str, Any]:
    if not frames:
        return ParsedFile.from_file(path, probe).raw_ffprobe.raw
    args = [get_executable("ffprobe"), "-v", "error", "-select_streams", "v:0", "-show_streams"]
    args.extend(["-show_frames", "-show_entries", "stream:frame=side_data_list", "-of", "json", str(path)])
    code, output = communicate_stdout(args, errors="replace")
    assert code == 0, output
    return json.loads(output)


def verify_output(path: Path, *, count: int, dolby: DolbyVision | None = None, hdr10plus: HDR10Plus | None = None) -> dict[str, Any]:
    data = probe(path, frames=True)
    frames = data["frames"]
    assert len(frames) == count
    if dolby is not None:
        previous = {}
        for record, frame in zip(dolby._records(dolby.prepare()), frames, strict=True):
            actual = next(side for side in frame["side_data_list"] if side["side_data_type"] == "Dolby Vision Metadata")
            metadata = record.get("vdr_dm_data") or previous
            previous = metadata
            for key in ("scene_refresh_flag", "source_min_pq", "source_max_pq"):
                assert actual[key] == metadata[key]
    if hdr10plus is not None:
        previous = None
        for record, frame in zip(hdr10plus._records(hdr10plus.prepare()), frames, strict=True):
            actual = next(
                (side for side in frame.get("side_data_list", []) if side["side_data_type"] == "HDR Dynamic Metadata SMPTE2094-40 (HDR10+)"),
                previous,
            )
            assert actual is not None
            previous = actual
            assert Fraction(actual["average_maxrgb"]) == Fraction(record["LuminanceParameters"]["AverageRGB"], 100000)
    return data
