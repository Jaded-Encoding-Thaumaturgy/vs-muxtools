import shlex
import subprocess
from vstools import vs, get_video_format
from muxtools import VideoFile, PathLike, make_output, warn, error
from muxtools.utils.dataclass import allow_extra, dataclass

from .base import FFMpegEncoder
from .types import LosslessPreset, ProResProfile

__all__ = ["FFV1", "ProRes"]


@dataclass(config=allow_extra)
class FFV1(FFMpegEncoder):
    """
    Uses ffmpeg to encode a clip to a lossless ffv1 stream.

    :param settings:        Can either be a string of your own settings or any of the 3 presets.
    """

    settings: str | LosslessPreset = LosslessPreset.MIDDLEGROUND

    def encode(self, clip: vs.VideoNode, outfile: PathLike | None = None) -> VideoFile:
        bits = get_video_format(clip).bits_per_sample
        if bits > 10:
            warn(f"You are encoding FFV1 with {bits} bits. It will be massive.", self, 1)
        _base = "-coder 1 -context 0 -g 1 -level 3 -threads 0"
        match self.settings:
            case LosslessPreset.SPEED:
                self.settings = _base + " -slices 30 -slicecrc 0"
            case LosslessPreset.COMPRESSION:
                self.settings = _base + " -slices 16 -slicecrc 1"
            case LosslessPreset.MIDDLEGROUND:
                self.settings = _base + " -slices 24 -slicecrc 1"
            case _:
                self.settings = self.settings

        out = make_output("encoded_ffv1", "mkv", user_passed=outfile)

        input_args, prop_args = self.input_args(clip)
        args = self._default_args() + input_args + ["-c:v", "ffv1"] + prop_args + self.get_custom_args()
        if self.settings:
            args.extend(shlex.split(self.settings))
        args.append(str(out))

        process = subprocess.Popen(args, stdin=subprocess.PIPE)
        self.update_process_affinity(process.pid)
        clip.output(process.stdin, y4m=True)
        process.communicate()

        enc_settings = self.get_mediainfo_settings(shlex.split(self.settings) + self.get_custom_args(), False)
        return VideoFile(out, tags=dict(ENCODER="ffmpeg FFV1", ENCODER_SETTINGS=enc_settings))


@dataclass(config=allow_extra)
class ProRes(FFMpegEncoder):
    """
    Uses ffmpeg's prores-ks encoder to encode a clip to a ProRes stream.\n
    Documentation for params and additional options can be viewed at: https://ffmpeg.org/ffmpeg-codecs.html#Private-Options-for-prores_002dks


    :param profile:         The encoder profile. Basically Quality settings.
                            Chooses the Standard/Default profile for 422 and the '4444' profile for 444 clips if None.
    """

    profile: ProResProfile | int | None = None

    def __post_init__(self):
        if isinstance(self.profile, int) and self.profile not in ProResProfile.__members__.values():
            raise error(f"{self.profile} is not a valid ProRes profile!", self)
        super().__post_init__()

    def encode(self, clip: vs.VideoNode, outfile: PathLike | None = None) -> VideoFile:
        clipf = get_video_format(clip)
        if clipf.subsampling_h != 0:
            raise error("ProRes only supports 422 and 444 subsampling clips.", self)
        if clipf.bits_per_sample > 12:
            raise error("ProRes only supports bitdepths at or below 12.", self)

        profile = self.profile
        if profile is None:
            profile = ProResProfile.DEFAULT if clipf.subsampling_w == 1 else ProResProfile.P4444

        if profile in range(0, 4) and clipf.subsampling_w != 1:
            raise error(f"Profile '{ProResProfile(profile).name}' only supports 422.", self)

        if profile in range(4, 5) and clipf.subsampling_w != 0:
            raise error(f"Profile '{ProResProfile(profile).name}' only supports 444.", self)

        out = make_output("prores", "mkv", user_passed=outfile)
        input_args, prop_args = self.input_args(clip)
        args = self._default_args() + input_args + ["-c:v", "prores_ks"] + prop_args + self.get_custom_args() + ["-profile", str(profile)]
        args.append(str(out))

        process = subprocess.Popen(args, stdin=subprocess.PIPE)
        self.update_process_affinity(process.pid)
        clip.output(process.stdin, y4m=True)
        process.communicate()
        enc_settings = self.get_mediainfo_settings(["-profile", str(profile)] + self.get_custom_args(), False)
        return VideoFile(out, tags=dict(ENCODER="ffmpeg prores_ks", ENCODER_SETTINGS=enc_settings))
