import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from muxtools import mux
from vsmuxtools import DolbyVision, HDR10Plus, SVTAV1, src_file, x265

from .hdr_support.validation import verify_output


HDR = Path(__file__).parent / "test-data" / "sample-files" / "hdr"
SETTINGS = "--preset ultrafast --crf 35 --no-open-gop --keyint 4 --min-keyint 4 --scenecut 0 --bframes 0 --pools 2 --frame-threads 1 --vbv-bufsize 30000 --vbv-maxrate 30000 --profile main10 --input-depth 10 --output-depth 10"
SVT_SETTINGS: dict[str, Any] = {"preset": 13, "crf": 40, "lp": 2}


@pytest.fixture(autouse=True)
def workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("vof_setup", json.dumps({"work_dir": str(tmp_path), "debug": False}))


def _source(name: str = "DV-P8-HDR10.mkv") -> src_file:
    return src_file(HDR / name, trim=(0, 8), cachemode=0, showprogress=False)


def test_x265_preserves_dovi_and_static_metadata_without_add_props(tmp_path: Path) -> None:
    source = _source()
    dolby = DolbyVision.from_source(source)
    encoder = x265(
        SETTINGS + " --colorprim 9 --transfer 16 --colormatrix 9 --range limited",
        add_props=False,
        dolby_vision=dolby,
        resumable=False,
        csv=False,
    )
    output = encoder.encode(source.init_cut(bits=10), tmp_path / "dv.265")
    data = verify_output(output.file, dolby=dolby, count=8)
    assert any(side["side_data_type"] == "Mastering display metadata" for side in data["frames"][0]["side_data_list"])


def test_x265_preserves_both_metadata(tmp_path: Path) -> None:
    source = _source("DV-P8-HDR10P.mkv")
    dolby, plus = DolbyVision.from_source(source), HDR10Plus.from_source(source)
    output = x265(SETTINGS, dolby_vision=dolby, hdr10plus=plus, resumable=False, csv=False).encode(source.init_cut(bits=10), tmp_path / "both.265")
    verify_output(output.file, dolby=dolby, hdr10plus=plus, count=8)


def test_x265_preserves_profile5(tmp_path: Path) -> None:
    source = _source("DV-P5.mkv")
    dolby = DolbyVision.from_source(source)
    output = x265(SETTINGS, dolby_vision=dolby, resumable=False, csv=False).encode(source.init_cut(bits=10), tmp_path / "profile5.265")
    verify_output(output.file, dolby=dolby, count=8)
    assert DolbyVision.from_source(output.file).resolved_profile == "5"


def test_x265_resume_uses_segment_metadata(tmp_path: Path) -> None:
    source = _source()
    clip = source.init_cut(bits=10)
    metadata = DolbyVision.from_source(source)
    output_path = tmp_path / "resumed.265"
    first = x265(SETTINGS, dolby_vision=metadata, resumable=True, csv=False).encode(clip, output_path)
    recovery = first.file.with_stem(first.file.stem + "_part_000")
    shutil.copyfile(first.file, recovery)
    resumed = x265(SETTINGS, dolby_vision=metadata, resumable=True, csv=False).encode(clip, output_path)
    verify_output(resumed.file, dolby=metadata, count=8)
    assert not recovery.exists()


def test_svt_ivf_mux_preserves_both_metadata_formats_and_profile10(tmp_path: Path) -> None:
    source = _source("DV-P8-HDR10P.mkv")
    dolby = DolbyVision.from_source(source)
    plus = HDR10Plus.from_source(source)
    encoder = SVTAV1(
        dolby_vision=dolby,
        hdr10plus=plus,
        **SVT_SETTINGS,
        light_photon_noise=False,
        resumable=False,
    )
    encoded = encoder.encode(source.init_cut(bits=10), tmp_path / "both.webm")
    assert encoded.file.suffix == ".ivf"
    assert encoder.force_webm is False
    output = mux(encoded.to_track(), outfile=tmp_path / "both.mkv")
    data = verify_output(output, dolby=dolby, hdr10plus=plus, count=8)
    config = next(side for side in data["streams"][0]["side_data_list"] if side["side_data_type"] == "DOVI configuration record")
    assert (config["dv_profile"], config["dv_bl_signal_compatibility_id"]) == (10, 1)


def test_svt_resume_preserves_segment_alignment(tmp_path: Path) -> None:
    source = _source("DV-P8-HDR10P.mkv")
    clip = source.init_cut(bits=10)
    dolby, plus = DolbyVision.from_source(source), HDR10Plus.from_source(source)
    options: dict[str, Any] = {**SVT_SETTINGS, "keyint": 4, "scd": 0, "enable_dg": 0}
    output_path = tmp_path / "svt-resume.mkv"
    first = SVTAV1(dolby_vision=dolby, hdr10plus=plus, light_photon_noise=False, **options).encode(clip, output_path)
    recovery = first.file.with_stem(first.file.stem + "_part_000")
    shutil.copyfile(first.file, recovery)
    resumed = SVTAV1(dolby_vision=dolby, hdr10plus=plus, light_photon_noise=False, **options).encode(clip, output_path)
    output = mux(resumed.to_track(), outfile=tmp_path / "svt-resume-final.mkv")
    verify_output(output, dolby=dolby, hdr10plus=plus, count=8)
    assert not recovery.exists()


def test_svt_essential_webm_preserves_hdr10plus_without_dolby() -> None:
    source = _source("DV-P8-HDR10P.mkv")
    plus = HDR10Plus.from_source(source)
    clip = source.init_cut(bits=10)
    encoder = SVTAV1(
        hdr10plus=plus,
        sd_clip=clip,
        sd_cache=False,
        light_photon_noise=False,
        resumable=False,
        **SVT_SETTINGS,
    )
    output = encoder.encode(clip, None)
    assert output.file.suffix == ".webm"
    verify_output(output.file, hdr10plus=plus, count=8)
