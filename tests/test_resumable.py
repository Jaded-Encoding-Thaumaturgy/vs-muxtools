from __future__ import annotations

from pathlib import Path

import pytest
from muxtools import get_executable
from muxtools.utils.env import communicate_stdout

from vsmuxtools.video.resumable import get_resume_parts, merge_parts
from .hdr_support.validation import probe


TEST_DATA = Path(__file__).parent / "test-data"
H264_FIXTURE = TEST_DATA / "sample-files" / "H264-10bit-FLAC-sample.mkv"


def _encode_segment(destination: Path, start: int, count: int) -> None:
    ffmpeg = get_executable("ffmpeg")
    args = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(H264_FIXTURE),
        "-map",
        "0:v:0",
        "-vf",
        f"trim=start_frame={start}:end_frame={start + count},setpts=PTS-STARTPTS",
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-g",
        "4",
        "-keyint_min",
        "4",
        "-sc_threshold",
        "0",
        "-f",
        "h264",
        str(destination),
    ]
    code, output = communicate_stdout(args)
    assert code == 0, output


@pytest.fixture
def encoded_parts(tmp_path: Path) -> tuple[Path, Path, Path]:
    output = tmp_path / "encoded.264"
    first = tmp_path / "encoded_part_000.264"
    last = tmp_path / "encoded_part_001.264"
    _encode_segment(first, 0, 8)
    _encode_segment(last, 8, 4)
    return output, first, last


def test_get_resume_parts_returns_retained_length_and_skips_only_trailing_data(encoded_parts: tuple[Path, Path, Path]) -> None:
    output, first, _ = encoded_parts
    unusable = output.with_name("encoded_part_001.264")
    unusable.write_bytes(b"interrupted encode")
    before = unusable.read_bytes()

    parts, retained_lengths, next_part = get_resume_parts(output)

    assert parts == [first]
    assert retained_lengths == [4]
    assert next_part == 1
    assert unusable.read_bytes() == before


def test_zero_restart_part_is_replaced_on_retry(encoded_parts: tuple[Path, Path, Path]) -> None:
    output, first, last = encoded_parts
    first.unlink()
    last.unlink()
    _encode_segment(first, 0, 2)

    parts, retained_lengths, next_part = get_resume_parts(output)
    assert parts == []
    assert retained_lengths == []
    assert next_part == 0

    _encode_segment(first, 0, 8)
    parts, retained_lengths, next_part = get_resume_parts(output)
    assert parts == [first]
    assert retained_lengths == [4]
    assert next_part == 1


def test_merge_uses_retained_length_and_removes_parts(encoded_parts: tuple[Path, Path, Path]) -> None:
    output, first, last = encoded_parts
    merge_parts(last, output, [4], [first])
    assert len(probe(output, frames=True)["frames"]) == 8
    assert not first.exists()
    assert not last.exists()
