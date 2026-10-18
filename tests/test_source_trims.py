from copy import deepcopy
from datetime import timedelta
from unittest.mock import Mock
import importlib

import numpy as np
import pytest

from muxtools import Trim, ensure_path
from vsmuxtools import src_file


test_dir = ensure_path(__file__, None).parent / "test-data"
sample_file = test_dir / "sample-files" / "H264-10bit-FLAC-sample.mkv"
pgs_file = test_dir / "sample-files" / "with-pgs" / "H265-PGS-sample.mkv"


def _source(trim=None) -> src_file:
    return src_file(sample_file, trim=trim, cachemode=0, showprogress=False)


def _assert_frames(actual, source, indices: list[int]) -> None:
    assert actual.num_frames == len(indices)
    for output_index, source_index in enumerate(indices):
        np.testing.assert_array_equal(
            np.asarray(actual[output_index].get_frame(0)[0]),
            np.asarray(source[source_index].get_frame(0)[0]),
        )


@pytest.mark.parametrize("trim", [(2, 5), [(2, 5)]])
def test_src_cut_accepts_tuple_and_singleton_list(trim) -> None:
    source = _source(trim)
    _assert_frames(source.src_cut, source.src, [2, 3, 4])


@pytest.mark.parametrize(
    "trim, expected",
    [
        ((2, 5), lambda raw: raw[2:5]),
        ((2, -2), lambda raw: raw[2:-2]),
        (
            [(8, 12), (2, 5), (2, 5), (20, None)],
            lambda raw: raw[8:12] + raw[2:5] + raw[2:5] + raw[20:],
        ),
    ],
)
def test_src_cut_matches_standard_vs_slicing(trim, expected) -> None:
    source = _source(trim)
    actual = source.src_cut
    standard = expected(source.src)

    assert actual.num_frames == standard.num_frames
    assert (actual.fps_num, actual.fps_den) == (standard.fps_num, standard.fps_den)
    for frame_number in range(standard.num_frames):
        actual_frame = actual.get_frame(frame_number)
        standard_frame = standard.get_frame(frame_number)
        for plane in range(standard.format.num_planes):
            np.testing.assert_array_equal(
                np.asarray(actual_frame[plane]),
                np.asarray(standard_frame[plane]),
            )


def test_src_cut_preserves_order_repetition_negative_bounds_and_input() -> None:
    trim = [(0, 5), (5, 6), (5, None)]
    original = deepcopy(trim)
    source = _source(trim)
    _assert_frames(source.src_cut, source.src, [*range(5), 5, *range(5, 26)])
    assert trim == original

    trim = [(-2, 3), (-2, -1)]
    original = deepcopy(trim)
    source = _source(trim)
    _assert_frames(source.src_cut, source.src, [0, 0, 0, 1, 2, 24])
    assert trim == original


def test_src_cut_trims_after_concatenating_inputs() -> None:
    source = src_file([sample_file, sample_file], trim=(24, 30), cachemode=0, showprogress=False)
    raw = _source().src
    _assert_frames(source.src_cut, raw, [24, 25, 0, 1, 2, 3])


@pytest.mark.parametrize(
    "trim, message",
    [((3, 3), "empty or reversed"), ((5, 2), "empty or reversed"), ((3, 0), "Slices cannot end with 0")],
)
def test_src_cut_rejects_invalid_ranges(trim: Trim, message: str) -> None:
    with pytest.raises(Exception, match=message):
        _source(trim).src_cut


def test_chapters_accept_singleton_and_guard_multiple_ranges(monkeypatch: pytest.MonkeyPatch) -> None:
    module = importlib.import_module("vsmuxtools.extension.chapters")
    monkeypatch.setattr(module, "parse_chapters_bdmv", lambda *_: [(timedelta(), "Start")])
    assert module.Chapters(_source([(2, 5)]), _print=False).chapters

    with pytest.raises(Exception, match="multiple trim"):
        module.Chapters(_source([(0, 2), (5, 8)]), _print=False)


def test_pgs_accepts_singleton_and_guards_multiple_ranges(monkeypatch: pytest.MonkeyPatch) -> None:
    module = importlib.import_module("vsmuxtools.extension.sub")
    subtitle = Mock()
    extractor = Mock(return_value=subtitle)
    monkeypatch.setattr(module.MTSubFilePGS, "extract_from", extractor)
    indexer = Mock(side_effect=AssertionError("PGS should not index video"))
    source = src_file(pgs_file, trim=[(2, None)], idx=indexer)

    assert module.SubFilePGS.extract_from(source) is subtitle.shift.return_value
    subtitle.shift.assert_called_once_with(-2, timesource=pgs_file, quiet=True)
    indexer.assert_not_called()

    with pytest.raises(Exception, match="multiple trim"):
        module.SubFilePGS.extract_from(src_file(pgs_file, trim=[(0, 2), (5, 8)], idx=indexer))
