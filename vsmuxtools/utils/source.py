from pathlib import Path
from typing import Callable, Sequence
from fractions import Fraction
from vstools import (
    vs,
    core,
    initialize_clip,
    KwargsT,
    ColorRangeT,
    MatrixT,
    TransferT,
    PrimariesT,
    DitherType,
    FieldBasedT,
    ChromaLocationT,
)
from muxtools import (
    Trim,
    PathLike,
    parse_m2ts_path,
    ensure_path_exists,
    info,
    get_workdir,
    get_temp_workdir,
    clean_temp_files,
    get_absolute_track,
    TrackType,
    GlobSearch,
    error,
    sanitize_trims,
)


__all__ = ["src_file", "SRC_FILE", "FileInfo", "src", "frames_to_samples", "f2s"]


class src_file:
    file: Path | list[Path]
    force_lsmas: bool = False
    force_bs: bool = False
    trim: Trim = None
    idx: Callable[[str], vs.VideoNode] | None = None
    idx_args = {}

    def __init__(
        self,
        file: PathLike | GlobSearch | Sequence[PathLike],
        force_lsmas: bool = False,
        trim: Trim = None,
        idx: Callable[[str], vs.VideoNode] | None = None,
        force_bs: bool = False,
        **kwargs,
    ):
        """
        Custom `FileInfo` kind of thing for convenience

        :param file:            Either a string based filepath or a Path object
        :param force_lsmas:     Forces the use of lsmas inside of the default indexer function.
        :param trim:            Can be a single trim or a sequence of trims.
        :param idx:             Indexer for the input file. Pass a function that takes a string in and returns a vs.VideoNode.
        :param force_bs:        Forces the use of bestsource inside of the default indexer function.
        """
        if isinstance(file, Sequence) and not isinstance(file, str) and len(file) == 1:
            file = file[0]

        self.file = (
            [ensure_path_exists(f, self) for f in file]
            if isinstance(file, Sequence) and not isinstance(file, str)
            else ensure_path_exists(file, self)
        )
        self.force_lsmas = force_lsmas
        self.force_bs = force_bs
        self.trim = trim
        self.idx = idx
        self.idx_args = kwargs

    def __call_indexer(self, fileIn: Path):
        if self.idx:
            return self.idx(str(fileIn.resolve()))
        else:
            return src(fileIn, self.force_lsmas, self.force_bs, **self.idx_args)

    def __index_clip(self):
        if isinstance(self.file, list):
            indexed = core.std.Splice([self.__call_indexer(f) for f in self.file])
        else:
            indexed = self.__call_indexer(self.file)
        cut = indexed
        if self.trim:
            self.trim = list(self.trim)
            if self.trim[0] is None:
                self.trim[0] = 0
            if self.trim[1] is None or self.trim[1] == 0:
                if self.trim[0] < 0:
                    cut = (indexed[0] * abs(self.trim[0])) + indexed
                else:
                    cut = indexed[self.trim[0] :]
            else:
                if self.trim[0] < 0:
                    cut = (indexed[0] * abs(self.trim[0])) + indexed[: self.trim[1]]
                else:
                    cut = indexed[self.trim[0] : self.trim[1]]
            self.trim = tuple(self.trim)

        if not isinstance(self.file, list) and self.file.suffix.lower() == ".dgi":
            if self.file.with_suffix(".m2ts").exists():
                self.file = self.file.with_suffix(".m2ts")
            else:
                self.file = parse_m2ts_path(self.file)

        setattr(self, "clip", indexed)
        setattr(self, "clip_cut", cut)

    @property
    def src(self) -> vs.VideoNode:
        if not hasattr(self, "clip"):
            self.__index_clip()
        return self.clip

    @property
    def src_cut(self) -> vs.VideoNode:
        if not hasattr(self, "clip_cut"):
            self.__index_clip()
        return self.clip_cut

    def init(
        self,
        bits: int | None = None,
        matrix: MatrixT | None = None,
        transfer: TransferT | None = None,
        primaries: PrimariesT | None = None,
        chroma_location: ChromaLocationT | None = None,
        color_range: ColorRangeT | None = None,
        field_based: FieldBasedT | None = None,
        strict: bool = False,
        dither_type: DitherType = DitherType.AUTO,
    ) -> vs.VideoNode:
        """
        Getter that calls `vstools.initialize_clip` on the src clip for convenience
        """
        return initialize_clip(
            self.src, bits, matrix, transfer, primaries, chroma_location, color_range, field_based, strict, dither_type, func=self.init
        )

    def init_cut(
        self,
        bits: int | None = None,
        matrix: MatrixT | None = None,
        transfer: TransferT | None = None,
        primaries: PrimariesT | None = None,
        chroma_location: ChromaLocationT | None = None,
        color_range: ColorRangeT | None = None,
        field_based: FieldBasedT | None = None,
        strict: bool = False,
        dither_type: DitherType = DitherType.AUTO,
    ) -> vs.VideoNode:
        """
        Getter that calls `vstools.initialize_clip` on the src_cut clip for convenience
        """
        return initialize_clip(
            self.src_cut, bits, matrix, transfer, primaries, chroma_location, color_range, field_based, strict, dither_type, func=self.init_cut
        )

    def get_audio(self, track: int = 0, **kwargs) -> vs.AudioNode:
        """
        Indexes the specified audio track from the input file(s).
        """
        file = self.file if isinstance(self.file, list) else [self.file]

        nodes = list[vs.AudioNode]()
        for f in file:
            absolute = get_absolute_track(f, track, TrackType.AUDIO)
            nodes.append(core.bs.AudioSource(str(f.resolve()), absolute, **kwargs))

        return nodes[0] if len(nodes) == 1 else core.std.AudioSplice(nodes)

    def get_audio_trimmed(self, track: int = 0, **kwargs) -> vs.AudioNode:
        """
        Gets the indexed audio track with the trim specified in the src_file.
        """
        node = self.get_audio(track, **kwargs)
        if self.trim:
            if self.trim[1] is None or self.trim[1] == 0:
                node = node[f2s(self.trim[0], node, self.src) :]
            else:
                node = node[f2s(self.trim[0], node, self.src) : f2s(self.trim[1], node, self.src)]
        return node

    @staticmethod
    def BDMV(
        root_dir: PathLike,
        playlist: int = 0,
        entries: int | list[int] | Trim | None = None,
        angle: int = 0,
        trim: Trim | None = None,
        force_lsmas: bool = False,
        force_bs: bool = False,
        idx: Callable[[str], vs.VideoNode] | None = None,
        **kwargs: KwargsT,
    ) -> "src_file":
        root_dir = ensure_path_exists(root_dir, "BDMV", True)
        mpls = core.mpls.Read(str(root_dir), playlist, angle)
        clips: list[str] = mpls["clip"]
        if entries is not None:
            if isinstance(entries, int):
                clips = clips[entries]
            elif isinstance(entries, list):
                entries = sanitize_trims(entries)
            else:
                if entries[0] is None and entries[1]:
                    clips = clips[: entries[1]]
                elif entries[1] is None:
                    clips = clips[entries[0] :]
                else:
                    clips = clips[entries[0] : entries[1]]
        return src_file(clips, force_lsmas, trim, idx, force_bs, **kwargs)


SRC_FILE = src_file
FileInfo = src_file


def src(filePath: PathLike, force_lsmas: bool = False, force_bs: bool = False, **kwargs: KwargsT) -> vs.VideoNode:
    """
    Uses lsmas for previewing and bestsource otherwise.
    Still supports dgi files directly if dgdecodenv is installed to not break existing scripts.

    :param filepath:        Path to video or dgi file
    :param force_lsmas:     Force the use of lsmas.LWLibavSource
    :param force_bs:        Force the use of bs.VideoSource. This takes priority over the force_lsmas param.
    :param kwargs:          Other arguments you may or may not wanna pass to the indexer.
    :return:                Video Node
    """
    filePath = ensure_path_exists(filePath, src)
    dgiFile = filePath.with_suffix(".dgi")
    if filePath.suffix.lower() == ".dgi" or dgiFile.exists():
        if not hasattr(core, "dgdecodenv"):
            raise error("Trying to use a dgi file without dgdecodenv installed.", src)
        return core.lazy.dgdecodenv.DGSource(str(filePath.resolve()) if not dgiFile.exists() else str(dgiFile.resolve()), **kwargs)

    has_bestsource, has_lsmas = hasattr(core, "bs"), hasattr(core, "lsmas")
    if not has_bestsource and not has_lsmas:
        raise error("Neither bestsource nor lsmas are installed.", src)
    if force_lsmas and not has_lsmas and not force_bs:
        raise error("You cannot force lsmas indexing without lsmas installed!", src)
    if force_bs and not has_bestsource:
        raise error("You cannot force bestsource indexing without bestsource installed!", src)

    is_previewing = False
    try:
        from vspreview import is_preview

        is_previewing = is_preview()
    except:
        pass

    if (is_previewing or force_lsmas) and not force_bs and has_lsmas:
        info(f"Indexing '{filePath.name}' using lsmas LWLibavSource", src)
        return core.lazy.lsmas.LWLibavSource(str(filePath.resolve()), **kwargs)
    else:
        info(f"Indexing '{filePath.name}' using bestsource.", src)
        show_progress = kwargs.pop("showprogress", True)
        return core.lazy.bs.VideoSource(str(filePath.resolve()), showprogress=show_progress, **kwargs)


def frames_to_samples(frame: int, sample_rate: vs.AudioNode | int = 48000, fps: vs.VideoNode | Fraction = Fraction(24000, 1001)) -> int:
    """
    Converts a frame number to a sample number

    :param frame:           The frame number
    :param sample_rate:     Can be a flat number like 48000 (=48 kHz) or an AudioNode to get the sample rate from
    :param fps:             Can be a Fraction or a VideoNode to get the fps from

    :return:                The sample number
    """
    if frame == 0:
        return 0
    sample_rate = sample_rate.sample_rate if isinstance(sample_rate, vs.AudioNode) else sample_rate
    fps = Fraction(fps.fps_num, fps.fps_den) if isinstance(fps, vs.VideoNode) else fps
    return int(sample_rate * (fps.denominator / fps.numerator) * frame)


f2s = frames_to_samples


def generate_keyframes(clip: vs.VideoNode, start_frame: int = 0) -> list[int]:
    clip = clip.resize.Bilinear(640, 360, format=vs.YUV410P8)
    clip = clip.wwxd.WWXD()
    if start_frame:
        clip = clip[start_frame:]

    frames = list[int]()
    for i in range(1, clip.num_frames):
        if clip.get_frame(i).props.Scenechange == 1:
            frames.append(i)

    return frames


def generate_qp_file(clip: vs.VideoNode, start_frame: int = 0) -> str:
    filepath = Path(get_workdir(), f"qpfile_{start_frame}.txt")
    temp = Path(get_temp_workdir(), "qpfile.txt")
    if filepath.exists():
        info("Reusing existing QP File.")
        return str(filepath.resolve())
    info("Generating QP File...")

    out = ""
    keyframes = generate_keyframes(clip, start_frame)

    for i in keyframes:
        out += f"{i} I -1\n"

    with open(temp, "w") as file:
        file.write(out)

    temp.rename(filepath)
    clean_temp_files()

    return str(filepath.resolve())
