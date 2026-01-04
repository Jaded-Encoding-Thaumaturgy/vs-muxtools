from pathlib import Path
from vstools import vs
from fractions import Fraction

from muxtools import do_audio as mt_audio
from muxtools import (
    PathLike,
    AudioFile,
    Encoder,
    Trimmer,
    Extractor,
    AutoEncoder,
    AutoTrimmer,
    AutoExtractor,
    Trim,
    danger,
    uniquify_path,
    get_workdir,
    ensure_path,
)
from muxtools.utils.types import TimeScale, TimeScaleT, TimeSourceT

from ..utils.source import src_file
from ..utils.audio import audio_async_render

__all__ = ["do_audio", "encode_audio", "export_audionode"]


def export_audionode(node: vs.AudioNode, outfile: PathLike | None = None) -> Path:
    """
    Exports an audionode to a wav/w64 file.

    :param node:            Your audionode
    :param outfile:         Custom output path if any

    :return:                Returns path
    """
    if not outfile:
        outfile = uniquify_path(Path(get_workdir(), "exported.wav"))

    outfile = ensure_path(outfile, export_audionode)
    with open(outfile, "wb") as bf:
        audio_async_render(node, bf)
    return outfile


def do_audio(
    fileIn: PathLike | src_file | vs.AudioNode,
    track: int = 0,
    trims: Trim | list[Trim] | None = None,
    timesource: TimeSourceT = None,
    timescale: TimeScaleT = TimeScale.MKV,
    num_frames: int = 0,
    extractor: Extractor | None = AutoExtractor(),
    trimmer: Trimmer | None = AutoTrimmer(),
    encoder: Encoder | None = AutoEncoder(),
    quiet: bool = True,
    output: PathLike | None = None,
) -> AudioFile:
    """
    One-liner to handle the whole audio processing

    :param fileIn:          Input file or src_file/FileInfo or AudioNode
    :param track:           Audio track number
    :param trims:           Frame ranges to trim and/or combine, e.g. (24, -24) or [(24, 500), (700, 900)]
                            If your passed src_file has a trim it will use it. Any other trims passed here will overwrite it.
    :param timesource:      The source of timestamps/timecodes. For details check the docstring on the type.\n
                            Will be taken from input if it's a src_file and assume the usual 24 if not.

    :param timescale:       Unit of time (in seconds) in terms of which frame timestamps are represented.\n
                            For details check the docstring on the type.

    :param num_frames:      Total number of frames, used for negative numbers in trims
                            Will be taken from input if it's a src_file

    :param extractor:       Tool used to extract the audio (Will default to None if an AudioNode gets passed, otherwise FFMpeg)
    :param trimmer:         Tool used to trim the audio
                            AutoTrimmer means it will choose ffmpeg for lossy and Sox for lossless

    :param encoder:         Tool used to encode the audio
                            AutoEncoder means it won't reencode lossy and choose opus otherwise

    :param quiet:           Whether the tool output should be visible
    :param output:          Custom output file or directory, extensions will be automatically added
    :return:                AudioFile Object containing file path, delays and source
    """
    if trims is not None:
        if isinstance(fileIn, src_file):
            danger("Other trims passed will overwrite whatever your src_file has!", do_audio, 1)
        if isinstance(fileIn, vs.AudioNode):
            danger("Trims won't be applied if you pass an Audionode. Just do them yourself before this lol.", do_audio, 1)
            trims = None
            trimmer = None

    if isinstance(fileIn, vs.AudioNode):
        extractor = None
        fileIn = export_audionode(fileIn)
    elif isinstance(fileIn, src_file):
        if not trims:
            trims = fileIn.trim

        clip = fileIn.src
        fileIn = fileIn.file
        if not num_frames:
            num_frames = clip.num_frames
        if timesource is None:
            timesource = Fraction(clip.fps_num, clip.fps_den)

    if timesource is None:
        timesource = Fraction(24000, 1001)

    # TODO: Check why this typecheck fails lol
    return mt_audio(fileIn, track, trims, timesource, timescale, num_frames, extractor, trimmer, encoder, quiet, output)  # type: ignore


encode_audio = do_audio
