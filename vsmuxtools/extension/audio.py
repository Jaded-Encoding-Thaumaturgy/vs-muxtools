from vstools import vs
from typing import overload
from fractions import Fraction

from muxtools import do_audio as mt_audio
from muxtools import PathLike, AudioFile, Encoder, Trimmer, Extractor, AutoEncoder, AutoTrimmer, FFMpeg, Trim, warn

from ..utils.src import src_file

__all__ = ["do_audio", "encode_audio"]


def do_audio(
    fileIn: PathLike | src_file,
    track: int = 0,
    trims: Trim | list[Trim] | None = None,
    fps: Fraction | None = None,
    num_frames: int = 0,
    extractor: Extractor = FFMpeg.Extractor(),
    trimmer: Trimmer | None = AutoTrimmer(),
    encoder: Encoder | None = AutoEncoder(),
    quiet: bool = True,
    output: PathLike | None = None,
) -> AudioFile:
    """
    One-liner to handle the whole audio processing

    :param fileIn:          Input file or src_file/FileInfo
    :param track:           Audio track number
    :param trims:           Frame ranges to trim and/or combine, e. g. (24, -24) or [(24, 500), (700, 900)]
                            If your passed src_file has a trim it will use it. Any other trims passed here will overwrite it.

    :param fps:             FPS Fraction used for the conversion to time
                            Will be taken from input if it's a src_file and assume the usual 24 if not.

    :param num_frames:      Total number of frames, used for negative numbers in trims
                            Will be taken from input if it's a src_file

    :param extractor:       Tool used to extract the audio
    :param trimmer:         Tool used to trim the audio
                            AutoTrimmer means it will choose ffmpeg for lossy and Sox for lossless

    :param encoder:         Tool used to encode the audio
                            AutoEncoder means it won't reencode lossy and choose opus otherwise

    :param quiet:           Whether or not the tool output should be visible
    :param output:          Custom output file or directory, extensions will be automatically added
    :return:                AudioFile Object containing file path, delays and source
    """
    if trims is not None:
        if isinstance(fileIn, src_file):
            warn("Other trims passed will overwrite whatever your src_file has!", do_audio, 1)

    if isinstance(fileIn, src_file):
        if not trims:
            trims = fileIn.trim
        clip = fileIn.src
        num_frames = clip.num_frames
        fps = Fraction(clip.fps_num, clip.fps_den)
        fileIn = fileIn.file
    else:
        fps = Fraction(24000, 1001)
    return mt_audio(fileIn, track, trims, fps, num_frames, extractor, trimmer, encoder, quiet, output)


encode_audio = do_audio
