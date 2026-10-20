"""Reusable Dolby Vision and HDR10+ metadata sidecar builders."""

from __future__ import annotations

import copy
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Self

from muxtools import (
    ParsedFile,
    TrackType,
    ensure_path_exists,
    error,
    get_executable,
    get_temp_workdir,
    get_workdir,
    info,
    run_commandline,
    uniquify_path,
)

from .timeline import (
    compile_editor_timeline,
    duplicate_frame,
    remove_ranges,
    resolve_ranges,
    segment_editor_config,
    select_ranges,
)


def _canonical_profile(profile: Any) -> str:
    value = str(profile).strip().lower()
    aliases = {"81": "8.1", "84": "8.4", "p5": "5", "p7": "7", "p8": "8"}
    value = aliases.get(value, value)
    if value not in {"5", "7", "8", "8.1", "8.4"}:
        raise error(f"Unsupported Dolby Vision profile {profile!r}.", DolbyVision)
    return value


class _DynamicMetadata:
    """Base implementation for metadata helpers backed by an upstream editor."""

    _kind = "dynamic"
    _suffix = ".sidecar"
    _tool = ""

    def __init__(self, source: Any, *, track: int = 0, metadata_path: Path | None = None) -> None:
        if not isinstance(track, int) or track < 0:
            raise error("track must be a non-negative video-track index.", self)
        file = getattr(source, "file", source)
        if isinstance(file, (list, tuple)):
            raise error("HDR metadata helpers support one source file; supply already aligned metadata for concatenated sources.", self)
        self._source = ensure_path_exists(file, self)
        self._track = track
        self._from_file = metadata_path is not None
        self._source_trim_value = copy.deepcopy(getattr(source, "trim", None)) if metadata_path is None else None
        self._mapping: list[int] | None = None
        self._records_cache: dict[Path, list[dict[str, Any]]] = {}
        self._operations: list[tuple[str, Any]] = []
        self._stages: list[dict[str, Any]] | None = None
        self._material: Path | None = self._source if self._from_file else None
        self._prepared: Path | None = None
        self._segments: dict[tuple[str, ...], Path] = {}

    @classmethod
    def from_source(cls, source: Any, *, track: int = 0) -> Self:
        """Create a helper that extracts metadata from one source video track.

        :param source: One video path or source object with a single ``.file``.
        :param track: Zero-based video-track index to extract.
        :return: A lazy metadata helper whose edits are applied by ``prepare``.
        """

        return cls(source, track=track)

    @classmethod
    def from_file(cls, path: os.PathLike[str] | str, **kwargs: Any) -> Self:
        """Create a helper from an existing metadata sidecar.

        :param path: Existing RPU or HDR10+ JSON sidecar.
        :param kwargs: Constructor options, including an explicit Dolby Vision profile.
        :return: A lazy metadata helper backed by the sidecar.
        """

        metadata_path = Path(path).expanduser()
        return cls(metadata_path, metadata_path=metadata_path, **kwargs)

    def _materialize_source(self) -> Path:
        if self._material is not None:
            return self._material
        if self._track and self._kind == "hdr10plus":
            raise error("hdr10plus_tool extracts the first video track. Supply a sidecar for another track using from_file().", self)
        track_suffix = f"_track{self._track}" if self._track else ""
        cached = get_workdir() / f"{self._source.stem}_{self._kind}{track_suffix}{self._suffix}"
        if cached.is_file():
            info(f"Reusing existing {self._kind} metadata.", self)
            self._material = cached
            return cached
        info(f"Extracting {self._kind} metadata...", self)
        with tempfile.TemporaryDirectory(prefix="hdr-source-", dir=get_temp_workdir()) as scratch_name:
            temporary = Path(scratch_name) / f"source{self._suffix}"
            command = "extract-rpu" if self._kind == "dolbyvision" else "extract"
            args = [get_executable(self._tool), command, "-i", str(self._source), "-o", str(temporary)]
            if self._track:
                track = ParsedFile.from_file(self._source, self).find_tracks(type=TrackType.VIDEO, relative_id=self._track, caller=self)[0]
                if track.raw_mkvmerge is None:
                    raise error("Video track selection requires an MKV input. Supply already extracted metadata with from_file().", self)
                args.extend(["--track-number", str(track.raw_mkvmerge.properties.number)])
            if run_commandline(args, quiet=True):
                raise error(f"{self._tool} metadata extraction failed.", self)
            temporary.replace(cached)
        self._material = cached
        return cached

    def _records(self, path: Path) -> list[dict[str, Any]]:
        path = path.resolve()
        if path in self._records_cache:
            return self._records_cache[path]
        if self._kind == "dolbyvision":
            with tempfile.TemporaryDirectory(prefix="hdr-export-", dir=get_temp_workdir()) as scratch_name:
                exported = Path(scratch_name) / "records.json"
                args = [get_executable("dovi_tool"), "export", "-i", str(path), "--data", f"all={exported}"]
                if run_commandline(args, quiet=True):
                    raise error("dovi_tool RPU export failed.", self)
                records = json.loads(exported.read_text(encoding="utf-8"))
        else:
            records = json.loads(path.read_text(encoding="utf-8"))["SceneInfo"]
        if not isinstance(records, list) or not records:
            raise error("Dynamic metadata source contains no frame records.", self)
        self._records_cache[path] = records
        return records

    def _ensure_mapping(self) -> list[int]:
        if self._mapping is None:
            source_records = self._records(self._materialize_source())
            self._mapping, self._stages = self._build_state(len(source_records))
            self._prepared = None
            self._segments.clear()
        return self._mapping

    def _build_state(self, source_count: int) -> tuple[list[int], list[dict[str, Any]]]:
        """Replay queued operations, compiling temporal edits at each metadata barrier."""

        mapping = list(range(source_count))
        stages: list[dict[str, Any]] = []
        stage_length = source_count
        if self._source_trim_value:
            mapping = select_ranges(mapping, self._source_trim_value, self)
            transition = compile_editor_timeline(mapping, stage_length)
            if transition:
                stages.append(transition)
            stage_length = len(mapping)
            mapping = list(range(stage_length))
        for kind, value in self._operations:
            if kind == "trim":
                mapping = select_ranges(mapping, value, self)
            elif kind == "remove":
                mapping = remove_ranges(mapping, value, self)
            elif kind == "duplicate":
                frame, count = value
                mapping = duplicate_frame(mapping, frame, count)
            elif kind in {"config", "crop", "active_area"}:
                transition = compile_editor_timeline(mapping, stage_length)
                if transition:
                    stages.append(transition)
                if kind == "config":
                    config = copy.deepcopy(value)
                elif kind == "crop":
                    config = self._active_area_config(True, value, len(mapping))
                else:
                    offsets, frames = value
                    config = self._active_area_config(offsets, frames, len(mapping))
                stages.append(config)
                stage_length = len(mapping)
                mapping = list(range(stage_length))
            else:
                raise error(f"Unknown queued HDR operation {kind!r}.", self)
        transition = compile_editor_timeline(mapping, stage_length)
        if transition:
            stages.append(transition)
        extra = self._extra_config()
        if extra:
            stages.insert(0, extra)
        return mapping, stages

    def _extra_config(self) -> dict[str, Any]:
        return {}

    def _active_area_config(self, offsets: Any, frames: Any, length: int) -> dict[str, Any]:
        raise error("Active-area edits are only available for Dolby Vision metadata.", self)

    @property
    def frame_count(self) -> int:
        """Return the number of frames in the complete prepared timeline.

        :return: The full edited count before any ``prepare(frames=...)`` segment.
        """

        return len(self._ensure_mapping())

    def trim(self, ranges: Any) -> Self:
        """Retain ordered, non-overlapping ranges from the current timeline.

        :param ranges: Inclusive-start, exclusive-end frame ranges using source trim semantics.
        :return: This helper, with the trim queued for ``prepare``.
        """

        self._operations.append(("trim", copy.deepcopy(ranges)))
        self._mapping = None
        return self

    def remove(self, ranges: Any) -> Self:
        """Remove ordered, non-overlapping ranges from the current timeline.

        :param ranges: Inclusive-start, exclusive-end frame ranges in the current timeline.
        :return: This helper, with the removal queued for ``prepare``.
        """

        self._operations.append(("remove", copy.deepcopy(ranges)))
        self._mapping = None
        return self

    def duplicate(self, frame: int, count: int = 1) -> Self:
        """Insert copies immediately after a current-timeline frame.

        :param frame: Current-timeline frame index to copy.
        :param count: Number of additional copies to insert.
        :return: This helper, with the duplication queued for ``prepare``.
        """

        self._operations.append(("duplicate", (frame, count)))
        self._mapping = None
        return self

    def edit(self, config: dict[str, Any]) -> Self:
        """Queue a validated upstream editor configuration.

        :param config: Metadata-only editor options; temporal keys use the chainable methods.
        :return: This helper, with the configuration queued for ``prepare``.
        """

        if not isinstance(config, dict):
            raise error("edit config must be a dictionary.", self)
        forbidden = set(config) & {"remove", "duplicate", "mode"}
        if forbidden:
            raise error(f"Use trim/remove/duplicate/convert_profile for editor keys: {', '.join(sorted(forbidden))}.", self)
        self._operations.append(("config", copy.deepcopy(config)))
        self._mapping = None
        return self

    def _run_editor(self, input_path: Path, config: dict[str, Any], destination: Path) -> Path:
        with tempfile.TemporaryDirectory(prefix="hdr-edit-", dir=get_temp_workdir()) as scratch_name:
            scratch = Path(scratch_name)
            config_path = scratch / "edits.json"
            config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
            temporary = scratch / destination.name
            args = [get_executable(self._tool), "editor", "-i", str(input_path), "-j", str(config_path), "-o", str(temporary)]
            if run_commandline(args, quiet=True):
                raise error(f"{self._tool} metadata editing failed.", self)
            temporary.replace(destination)
        return destination

    def prepare(self, output: os.PathLike[str] | str | None = None, *, frames: Any = None) -> Path:
        """Prepare a reusable metadata sidecar, optionally sliced to one segment.

        :param output: Optional destination path for a sidecar copy.
        :param frames: Optional contiguous ``[start:end)`` segment of the full timeline.
        :return: The prepared sidecar path; queued edits remain reusable.
        """

        source = self._materialize_source()
        mapping = self._ensure_mapping()
        if self._prepared is None:
            current = source
            if self._stages:
                info(f"Preparing {self._kind} metadata...", self)
                destination = Path(uniquify_path(get_workdir() / f"{self._source.stem}_{self._kind}_edited{self._suffix}"))
                with tempfile.TemporaryDirectory(prefix="hdr-stages-", dir=get_temp_workdir()) as scratch_name:
                    for index, config in enumerate(self._stages):
                        stage_output = destination if index == len(self._stages) - 1 else Path(scratch_name) / f"stage-{index}{self._suffix}"
                        current = self._run_editor(current, config, stage_output)
            self._prepared = current

        segment = segment_editor_config(len(mapping), frames)
        if not segment:
            prepared = self._prepared
        else:
            key = tuple(segment["remove"])
            if key not in self._segments:
                segment_path = Path(uniquify_path(get_workdir() / f"{self._prepared.stem}_segment{self._suffix}"))
                self._segments[key] = self._run_editor(self._prepared, segment, segment_path)
            prepared = self._segments[key]

        if output is None:
            return prepared
        destination = Path(output).expanduser().resolve()
        if destination in (self._source, source.resolve()):
            raise error("Refusing to overwrite metadata input with its prepared output.", self)
        if destination != prepared:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(prepared, destination)
        return destination


class DolbyVision(_DynamicMetadata):
    """Build Dolby Vision RPU sidecars with dovi_tool."""

    _kind = "dolbyvision"
    _suffix = ".rpu"
    _tool = "dovi_tool"

    def __init__(self, source: Any, *, track: int = 0, metadata_path: Path | None = None, profile: Any = None) -> None:
        super().__init__(source, track=track, metadata_path=metadata_path)
        self._declared_profile = _canonical_profile(profile) if profile is not None else None
        self._target_profile: str | None = None

    @property
    def resolved_profile(self) -> str:
        """Return the canonical source or explicitly requested Dolby Vision profile.

        :return: A canonical profile string, preserving unknown Profile 8 compatibility.
        """

        if self._target_profile is not None:
            return self._target_profile
        return self._input_profile()

    def _input_profile(self) -> str:
        """Resolve the original profile without considering a queued conversion."""

        if self._declared_profile is not None:
            return self._declared_profile
        if not self._from_file:
            stream = ParsedFile.from_file(self._source, self).find_tracks(type=TrackType.VIDEO, relative_id=self._track, caller=self)[0].raw_ffprobe
            for side_data in stream.raw.get("side_data_list", stream.side_data_list):
                if side_data.get("side_data_type") != "DOVI configuration record":
                    continue
                profile = str(side_data.get("dv_profile", ""))
                compatibility = side_data.get("dv_bl_signal_compatibility_id")
                if profile == "8" and compatibility in (1, "1"):
                    return "8.1"
                if profile == "8" and compatibility in (4, "4"):
                    return "8.4"
                if profile:
                    return _canonical_profile(profile)
        records = self._records(self._materialize_source())
        values = {str(record.get("dovi_profile")) for record in records if record.get("dovi_profile") is not None}
        if len(values) != 1:
            raise error("Dolby Vision RPU has no single identifiable profile.", self)
        return _canonical_profile(values.pop())

    def convert_profile(self, profile: Any) -> Self:
        """Request an explicit RPU conversion to Dolby Vision Profile 8.1.

        :param profile: Target profile; only P5/P7 to 8.1 is supported.
        :return: This helper, with conversion deferred until ``prepare``.

        P5 conversion changes RPU signaling only; the caller must convert pixels separately.
        P7 FEL handling likewise remains the caller's responsibility.
        """

        target = _canonical_profile(profile)
        self._target_profile = target
        self._mapping = None
        return self

    def crop_active_area(self, *, frames: Any = None) -> Self:
        """Reset active-area offsets to zero for all or selected frames.

        :param frames: Optional current-timeline ranges receiving the crop.
        :return: This helper, with the active-area edit queued for ``prepare``.
        """

        if frames is None:
            self._operations.append(("config", {"active_area": {"crop": True}}))
        else:
            self._operations.append(("crop", copy.deepcopy(frames)))
        self._mapping = None
        return self

    def active_area(self, left: int, top: int, right: int, bottom: int, *, frames: Any = None) -> Self:
        """Set explicit active-area offsets for all or selected frames.

        :param left: Active-area left offset in pixels.
        :param top: Active-area top offset in pixels.
        :param right: Active-area right offset in pixels.
        :param bottom: Active-area bottom offset in pixels.
        :param frames: Optional current-timeline ranges receiving the offsets.
        :return: This helper, with the active-area edit queued for ``prepare``.
        """

        values = (left, top, right, bottom)
        if any(not isinstance(value, int) or value < 0 for value in values):
            raise error("Active-area offsets must be non-negative integers.", self)
        self._operations.append(("active_area", ((left, top, right, bottom), copy.deepcopy(frames))))
        self._mapping = None
        return self

    def _active_area_config(self, offsets: Any, frames: Any, length: int) -> dict[str, Any]:
        if offsets is True:
            if frames is None:
                return {"active_area": {"crop": True}}
            offsets = (0, 0, 0, 0)
        left, top, right, bottom = offsets
        preset = {"id": 0, "left": left, "right": right, "top": top, "bottom": bottom}
        if frames is None:
            edits = {"all": 0}
        else:
            edits = {}
            for start, end in resolve_ranges(frames, length, self):
                first, last = max(0, start), length if end is None else end
                edits[f"{first}-{last - 1}"] = 0
        return {"active_area": {"presets": [preset], "edits": edits}}

    def _extra_config(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        if self._target_profile is not None:
            source = self._input_profile()
            if self._target_profile == source:
                return result
            if self._target_profile != "8.1" or source not in {"5", "7"}:
                raise error(f"Unsupported Dolby Vision conversion {source} -> {self._target_profile}; only P5/P7 to P8.1 is supported.", self)
            result["mode"] = 3 if source == "5" else 2
        return result


class HDR10Plus(_DynamicMetadata):
    """Build HDR10+ JSON sidecars with hdr10plus_tool."""

    _kind = "hdr10plus"
    _suffix = ".json"
    _tool = "hdr10plus_tool"
