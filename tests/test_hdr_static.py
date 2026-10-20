from pathlib import Path

from pydantic import ValidationError
import pytest

from muxtools import ensure_path
from vsmuxtools import src_file
from vsmuxtools.video.clip_metadata import HDR10Metadata, hdr10_args


test_dir = ensure_path(__file__, None).parent / "test-data"
hdr_dir = Path(test_dir) / "sample-files" / "hdr"


def _clip(name: str):
    return src_file(hdr_dir / name, cachemode=0, showprogress=False).src


def test_p7_hdr10_static_metadata_and_encoder_arguments() -> None:
    clip = _clip("DV-P7-FEL-HDR10.mkv")
    metadata = HDR10Metadata.from_clip(clip)

    assert metadata.primaries == ((0.68, 0.32), (0.265, 0.69), (0.15, 0.06))
    assert metadata.white_point == (0.3127, 0.329)
    assert metadata.min_luminance == 0.0005
    assert metadata.max_luminance == 1000.0
    assert (metadata.max_cll, metadata.max_fall) == (1000, 400)
    assert hdr10_args(clip, x265=True) == [
        "--master-display",
        "G(13250,34500)B(7500,3000)R(34000,16000)WP(15635,16450)L(10000000,5)",
        "--max-cll",
        "1000,400",
    ]
    assert hdr10_args(clip, x265=False) == [
        "--mastering-display",
        "G(0.265,0.69)B(0.15,0.06)R(0.68,0.32)WP(0.3127,0.329)L(1000.0,0.0005)",
        "--content-light",
        "1000,400",
    ]


def test_p8_omits_absent_content_light_level() -> None:
    clip = _clip("DV-P8-HDR10.mkv")
    metadata = HDR10Metadata.from_clip(clip)

    assert metadata.max_cll is None
    assert metadata.max_fall is None
    args = hdr10_args(clip, x265=True)
    assert "--max-cll" not in args
    assert "1000,400" not in args


def test_explicit_static_metadata_override_and_cli_precedence() -> None:
    original = _clip("DV-P7-FEL-HDR10.mkv")
    filtered = original.std.RemoveFrameProps()
    override = HDR10Metadata.from_clip(original)
    assert hdr10_args(filtered, x265=False, hdr10=override) == hdr10_args(original, x265=False)
    existing = [
        "--mastering-display",
        "manual-display",
        "--content-light",
        "1,1",
    ]
    args = hdr10_args(filtered, x265=False, hdr10=override, existing_args=existing)

    assert args == []


def test_static_metadata_requires_complete_group() -> None:
    with pytest.raises(ValidationError, match="supplied together"):
        HDR10Metadata(min_luminance=0.0001)


def test_incomplete_automatic_mastering_group_is_omitted() -> None:
    clip = _clip("DV-P7-FEL-HDR10.mkv")
    incomplete_mastering = clip.std.RemoveFrameProps("MasteringDisplayMaxLuminance")
    metadata = HDR10Metadata.from_clip(incomplete_mastering)
    assert metadata.primaries is None
    assert (metadata.max_cll, metadata.max_fall) == (1000, 400)
