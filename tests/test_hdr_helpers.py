from __future__ import annotations

import json
from pathlib import Path

import pytest
from muxtools import get_executable, run_commandline

from vsmuxtools.video.hdr import DolbyVision, HDR10Plus
from vsmuxtools import src_file


HDR_FIXTURES = Path(__file__).parent / "test-data" / "sample-files" / "hdr"


@pytest.fixture(autouse=True)
def workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("vof_setup", json.dumps({"work_dir": str(tmp_path), "debug": False}))


def test_dolby_vision_fixture_prepares_real_rpu(tmp_path: Path) -> None:
    source = HDR_FIXTURES / "DV-P8-HDR10.mkv"
    original = DolbyVision.from_source(source).prepare(tmp_path / "original.rpu")
    original_records = DolbyVision.from_file(original)._records(original)

    helper = DolbyVision.from_source(source).trim((2, 8)).duplicate(2, 2)
    prepared = helper.prepare(tmp_path / "metadata.rpu")

    records = helper._records(prepared)
    expected = original_records[2:5] + original_records[4:5] * 2 + original_records[5:8]
    assert [record["rpu_data_crc32"] for record in records] == [record["rpu_data_crc32"] for record in expected]


def test_source_trim_snapshot_preserves_leading_padding(tmp_path: Path) -> None:
    source = src_file(HDR_FIXTURES / "DV-P8-HDR10.mkv", trim=[(-2, 3)])
    helper = DolbyVision.from_source(source)
    assert isinstance(source.trim, list)
    source.trim[:] = [(5, 10)]

    prepared = helper.prepare(tmp_path / "padded.rpu")
    records = helper._records(prepared)
    original = DolbyVision.from_source(HDR_FIXTURES / "DV-P8-HDR10.mkv").prepare(tmp_path / "original.rpu")
    original_records = helper._records(original)
    assert [record["rpu_data_crc32"] for record in records] == [
        original_records[0]["rpu_data_crc32"],
        original_records[0]["rpu_data_crc32"],
        original_records[0]["rpu_data_crc32"],
        original_records[1]["rpu_data_crc32"],
        original_records[2]["rpu_data_crc32"],
    ]


def test_dolby_vision_file_profile_8_stays_unknown_without_declaration(tmp_path: Path) -> None:
    source = HDR_FIXTURES / "DV-P8-HDR10.mkv"
    prepared = DolbyVision.from_source(source).prepare(tmp_path / "metadata.rpu")

    from_file = DolbyVision.from_file(prepared)
    assert from_file.resolved_profile == "8"
    assert DolbyVision.from_file(prepared, profile="8.1").resolved_profile == "8.1"


@pytest.mark.parametrize(("filename", "expected_mode"), [("DV-P5.mkv", "8.1"), ("DV-P7-FEL-HDR10.mkv", "8.1")])
def test_dolby_vision_profile_conversion_is_explicit(tmp_path: Path, filename: str, expected_mode: str) -> None:
    helper = DolbyVision.from_source(HDR_FIXTURES / filename).convert_profile(expected_mode)
    prepared = helper.prepare(tmp_path / f"{Path(filename).stem}.rpu")

    assert helper.resolved_profile == expected_mode
    assert DolbyVision.from_file(prepared).resolved_profile == "8"


def test_dolby_vision_file_conversion_resolves_input_profile_at_prepare(tmp_path: Path) -> None:
    source = DolbyVision.from_source(HDR_FIXTURES / "DV-P5.mkv").prepare(tmp_path / "source.rpu")
    helper = DolbyVision.from_file(source).convert_profile("8.1")

    prepared = helper.prepare(tmp_path / "converted.rpu")

    assert helper.resolved_profile == "8.1"
    assert DolbyVision.from_file(prepared).resolved_profile == "8"


def test_hdr10plus_fixture_preserves_scene_info_and_segments(tmp_path: Path) -> None:
    source = HDR_FIXTURES / "DV-P8-HDR10P.mkv"
    helper = HDR10Plus.from_source(source)

    original = HDR10Plus.from_source(source).prepare(tmp_path / "original.json")
    original_records = helper._records(original)
    prepared = helper.prepare(tmp_path / "metadata.json", frames=(20, 30))
    records = helper._records(prepared)
    indices = {"SceneFrameIndex", "SceneId", "SequenceFrameIndex"}
    for actual, expected in zip(records, original_records[20:30], strict=True):
        assert {key: value for key, value in actual.items() if key not in indices} == {
            key: value for key, value in expected.items() if key not in indices
        }


def test_active_area_lineage_survives_trim_duplicate_and_remove(tmp_path: Path) -> None:
    helper = (
        DolbyVision.from_source(HDR_FIXTURES / "DV-P8-HDR10.mkv")
        .trim((10, 20))
        .active_area(1, 2, 3, 4, frames=(0, 2))
        .duplicate(0)
        .remove((0, 1))
        .crop_active_area(frames=(2, 3))
    )
    prepared = helper.prepare(tmp_path / "active-area.rpu")
    records = helper._records(prepared)
    first_l5 = records[0]["vdr_dm_data"]["cmv29_metadata"]["ext_metadata_blocks"][-2]["Level5"]
    second_l5 = records[1]["vdr_dm_data"]["cmv29_metadata"]["ext_metadata_blocks"][-2]["Level5"]
    assert first_l5 == {
        "active_area_left_offset": 1,
        "active_area_right_offset": 3,
        "active_area_top_offset": 2,
        "active_area_bottom_offset": 4,
    }
    assert second_l5["active_area_top_offset"] == 2
    assert records[2]["vdr_dm_data"]["cmv29_metadata"]["ext_metadata_blocks"][-2]["Level5"]["active_area_top_offset"] == 0
    assert records[3]["vdr_dm_data"]["cmv29_metadata"]["ext_metadata_blocks"][-2]["Level5"]["active_area_top_offset"] == 120


def test_temporal_reordering_is_rejected() -> None:
    helper = HDR10Plus.from_source(HDR_FIXTURES / "DV-P8-HDR10P.mkv")
    with pytest.raises(Exception):
        helper.trim([(4, 8), (2, 3)]).prepare()


def test_cached_source_reuse_does_not_overwrite_prepared_input() -> None:
    source = HDR_FIXTURES / "DV-P8-HDR10.mkv"
    original = DolbyVision.from_source(source).prepare()
    original_bytes = original.read_bytes()

    helper = DolbyVision.from_source(source).trim((2, 10))
    prepared = helper.prepare()

    assert prepared.read_bytes() != original_bytes
    with pytest.raises(Exception, match="Refusing to overwrite"):
        helper.prepare(output=original)
    assert original.read_bytes() == original_bytes


def test_dolby_track_selection_uses_container_track_number(tmp_path: Path) -> None:
    mkvmerge = get_executable("mkvmerge")
    source = tmp_path / "multiple-tracks.mkv"
    assert run_commandline([mkvmerge, "-o", str(source), str(HDR_FIXTURES / "DV-P5.mkv"), str(HDR_FIXTURES / "DV-P8-HDR10.mkv")]) <= 1
    helper = DolbyVision.from_source(source, track=1)
    original = DolbyVision.from_source(HDR_FIXTURES / "DV-P8-HDR10.mkv").prepare()

    assert helper.prepare().read_bytes() == original.read_bytes()


@pytest.mark.parametrize("metadata_type", [DolbyVision, HDR10Plus])
def test_direct_hevc_bitstream_input(tmp_path: Path, metadata_type: type[DolbyVision] | type[HDR10Plus]) -> None:
    mkvextract = get_executable("mkvextract")
    source = HDR_FIXTURES / "DV-P8-HDR10P.mkv"
    bitstream = tmp_path / "source.hevc"
    assert run_commandline([mkvextract, str(source), "tracks", f"0:{bitstream}"]) == 0

    original = metadata_type.from_source(source).prepare()
    prepared = metadata_type.from_source(bitstream).prepare()
    assert prepared.read_bytes() == original.read_bytes()
