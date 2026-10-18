from unittest.mock import Mock
import numpy as np
import pytest
import vapoursynth as vs

from muxtools import Trim, ensure_path
from vsmuxtools import src_file
from vsmuxtools.extension import audio as audio_module


test_dir = ensure_path(__file__, None).parent.parent / "test-data"
sample_file = test_dir / "sample-files" / "H264-10bit-FLAC-sample.mkv"


def _source(trim: Trim | list[Trim] | None = None) -> src_file:
    return src_file(sample_file, trim=trim, cachemode=0, showprogress=False)


def _samples(node) -> np.ndarray:
    channels = [[] for _ in range(node.num_channels)]
    for frame in node.frames(close=True):
        for channel in range(node.num_channels):
            channels[channel].append(np.asarray(frame[channel]).copy())
    return np.stack([np.concatenate(channel)[: node.num_samples] for channel in channels], axis=1)


@pytest.mark.parametrize("trim", [(2, 5), [(2, 5)]])
def test_get_audio_trimmed_accepts_tuple_and_singleton_list(trim: Trim | list[Trim]) -> None:
    source = _source(trim)
    raw = _samples(source.get_audio(cachemode=0, showprogress=False))
    actual = _samples(source.get_audio_trimmed(cachemode=0, showprogress=False))
    np.testing.assert_array_equal(actual, raw[4004:10010])


def test_get_audio_trimmed_preserves_order_padding_and_negative_bounds() -> None:
    trim: list[Trim] = [(-2, 3), (-2, -1), (2, 4), (2, 4)]
    source = _source(trim)
    raw = _samples(source.get_audio(cachemode=0, showprogress=False))
    actual = _samples(source.get_audio_trimmed(cachemode=0, showprogress=False))
    expected = np.concatenate([np.zeros((4004, raw.shape[1]), dtype=raw.dtype), raw[:6006], raw[48048:49152], raw[4004:8008], raw[4004:8008]])
    np.testing.assert_array_equal(actual, expected)
    assert trim == [(-2, 3), (-2, -1), (2, 4), (2, 4)]


def test_get_audio_trimmed_clips_short_audio_keeps_tail_and_rejects_no_samples() -> None:
    source = _source((24, 26))
    raw = _samples(source.get_audio(cachemode=0, showprogress=False))
    actual = _samples(source.get_audio_trimmed(cachemode=0, showprogress=False))
    np.testing.assert_array_equal(actual, raw[48048:49152])

    short_video = source.src[:12]
    open_end = src_file(sample_file, trim=(0, None), idx=lambda _: short_video)
    np.testing.assert_array_equal(_samples(open_end.get_audio_trimmed(cachemode=0, showprogress=False)), raw)
    source.trim = (25, 26)
    with pytest.raises(Exception, match="no available audio"):
        source.get_audio_trimmed(cachemode=0, showprogress=False)


def test_get_audio_trimmed_uses_fractional_boundaries_and_rejects_variable_fps() -> None:
    source = _source((1, 2))
    raw = _samples(source.get_audio(cachemode=0, showprogress=False))
    actual = _samples(source.get_audio_trimmed(cachemode=0, showprogress=False))
    assert len(actual) == 2002
    np.testing.assert_array_equal(actual, raw[2002:4004])

    real = _source().src
    variable = vs.core.std.Splice([real, real.std.AssumeFPS(fpsnum=25, fpsden=1)])
    source = src_file(sample_file, trim=(1, 2), idx=lambda _: variable, cachemode=0, showprogress=False)
    with pytest.raises(Exception, match="constant"):
        source.get_audio_trimmed(cachemode=0, showprogress=False)


def test_get_audio_trimmed_concatenates_real_inputs_before_trimming() -> None:
    source = src_file([sample_file, sample_file], trim=(24, 30), cachemode=0, showprogress=False)
    single = _source()
    raw_audio = _samples(single.get_audio(cachemode=0, showprogress=False))
    combined = np.concatenate([raw_audio, raw_audio])
    actual = _samples(source.get_audio_trimmed(cachemode=0, showprogress=False))
    np.testing.assert_array_equal(actual, combined[48048:60060])


def test_do_audio_inherits_only_for_none_and_copies_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    source = _source((8, None))
    process = Mock(return_value=object())
    monkeypatch.setattr(audio_module, "mt_audio", process)

    audio_module.do_audio(source, extractor=None, trimmer=None, encoder=None)
    assert process.call_args.args[2] == (8, None)

    override: list[Trim] = [(0, 2), (8, None)]
    process.reset_mock()
    audio_module.do_audio(source, trims=override, extractor=None, trimmer=None, encoder=None)
    assert process.call_args.args[2] == override
    assert process.call_args.args[2] is not override

    process.reset_mock()
    audio_module.do_audio(source, trims=[], extractor=None, trimmer=None, encoder=None)
    assert process.call_args.args[2] == []
