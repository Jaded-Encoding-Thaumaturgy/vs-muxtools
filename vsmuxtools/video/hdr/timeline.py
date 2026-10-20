"""Frame timeline helpers shared by the dynamic HDR metadata builders."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from itertools import groupby
from typing import Any, TypeAlias

from muxtools import error
from vsmuxtools.utils.source import _resolve_trims


FrameRange: TypeAlias = tuple[int, int | None]


def _as_ranges(ranges: Any, caller: Any) -> list[Any]:
    if ranges is None:
        return []
    if isinstance(ranges, tuple) and len(ranges) == 2 and all(x is None or isinstance(x, int) for x in ranges):
        return [ranges]
    if isinstance(ranges, list) and len(ranges) == 2 and all(x is None or isinstance(x, int) for x in ranges):
        return [tuple(ranges)]
    if isinstance(ranges, Sequence) and not isinstance(ranges, (str, bytes)):
        return list(ranges)
    raise error("Frame ranges must be a (start, end) pair or a sequence of pairs.", caller)


def resolve_ranges(ranges: Any, num_frames: int, caller: Any = "HDR metadata") -> list[FrameRange]:
    """Resolve Python frame ranges using the source helper's negative-bound semantics."""

    values = _as_ranges(ranges, caller)
    if not values:
        return []
    resolved = _resolve_trims(values, num_frames, caller)

    previous_end = 0
    for index, (start, end) in enumerate(resolved):
        actual_start = max(0, start)
        actual_end = num_frames if end is None else end
        if index and actual_start < previous_end:
            raise error("Retained frame ranges must be forward and non-overlapping.", caller)
        previous_end = actual_end
    return resolved


def select_ranges(mapping: Sequence[int], ranges: Any, caller: Any = "HDR metadata") -> list[int]:
    """Select ranges from a timeline, retaining the source helper's leading padding behavior."""

    if not ranges:
        return list(mapping)
    resolved = resolve_ranges(ranges, len(mapping), caller)
    selected: list[int] = []
    for start, end in resolved:
        first = max(0, start)
        last = len(mapping) if end is None else end
        if start < 0:
            if not mapping:
                raise error("Cannot pad an empty metadata timeline.", caller)
            selected.extend(mapping[0] for _ in range(-start))
        selected.extend(mapping[first:last])
    return selected


def remove_ranges(mapping: Sequence[int], ranges: Any, caller: Any = "HDR metadata") -> list[int]:
    """Remove inclusive editor ranges expressed as Python exclusive-end ranges."""

    if not ranges:
        return list(mapping)
    resolved = resolve_ranges(ranges, len(mapping), caller)
    removed = [False] * len(mapping)
    for start, end in resolved:
        if start < 0:
            raise error("Negative starts are only supported for retained source trims.", caller)
        last = len(mapping) if end is None else end
        for index in range(start, last):
            removed[index] = True
    result = [frame for index, frame in enumerate(mapping) if not removed[index]]
    if not result:
        raise error("Removing all metadata frames is not supported.", caller)
    return result


def duplicate_frame(mapping: Sequence[int], frame: int, count: int = 1) -> list[int]:
    """Insert copies immediately after a current-timeline frame."""

    if not isinstance(frame, int) or frame < 0 or frame >= len(mapping):
        raise error(f"Duplicate frame {frame!r} is outside the current timeline.", duplicate_frame)
    if not isinstance(count, int) or count < 1:
        raise error("Duplicate count must be a positive integer.", duplicate_frame)
    index = frame + 1
    copies = [mapping[frame]] * count
    return list(mapping[:index]) + copies + list(mapping[index:])


def editor_ranges(indices: Iterable[int]) -> list[str]:
    """Collapse sorted source indices into inclusive ranges for upstream editor configs."""

    values = sorted(set(indices))
    if not values:
        return []
    result: list[str] = []
    start = previous = values[0]
    for value in values[1:]:
        if value == previous + 1:
            previous = value
            continue
        result.append(str(start) if start == previous else f"{start}-{previous}")
        start = previous = value
    result.append(str(start) if start == previous else f"{start}-{previous}")
    return result


def compile_editor_timeline(mapping: Sequence[int], source_length: int) -> dict[str, Any]:
    """Compile a monotonic mapping into dovi_tool/hdr10plus_tool editor operations."""

    if source_length < 1:
        raise error("Metadata source contains no frames.", compile_editor_timeline)
    if not mapping:
        raise error("The requested timeline contains no frames.", compile_editor_timeline)
    sources = list(mapping)
    if any(index < 0 or index >= source_length for index in sources):
        raise error("Metadata timeline contains a source frame outside the source range.", compile_editor_timeline)

    runs = [(source, sum(1 for _ in group)) for source, group in groupby(sources)]
    retained = [source for source, _ in runs]
    retained_set = set(retained)
    if len(retained) != len(retained_set):
        raise error("Metadata timeline reorders or repeats a retained source range.", compile_editor_timeline)

    if any(left >= right for left, right in zip(retained, retained[1:])):
        raise error("Metadata timeline must remain in forward source order.", compile_editor_timeline)

    missing = [index for index in range(source_length) if index not in retained_set]
    config: dict[str, Any] = {}
    if missing:
        # The upstream editors apply list entries to the shortened timeline.
        # Removing from the end keeps all earlier indices stable.
        config["remove"] = list(reversed(editor_ranges(missing)))

    duplicates = [{"source": position, "offset": position, "length": count - 1} for position, (_, count) in enumerate(runs) if count > 1]
    if duplicates:
        config["duplicate"] = duplicates
    return config


def segment_editor_config(length: int, frames: Any) -> dict[str, Any]:
    """Create a range-removal config for a contiguous prepared-output segment."""

    if frames is None:
        return {}
    if isinstance(frames, slice):
        if frames.step not in (None, 1):
            raise error("Metadata segments must use a contiguous frame slice.", segment_editor_config)
        start, end = frames.start or 0, frames.stop if frames.stop is not None else length
    elif isinstance(frames, tuple) and len(frames) == 2:
        start, end = frames
    elif isinstance(frames, list) and len(frames) == 2:
        start, end = frames
    else:
        raise error("frames must be a slice or a (start, end) segment.", segment_editor_config)
    if not isinstance(start, int) or not isinstance(end, int):
        raise error("Metadata segment boundaries must be integers.", segment_editor_config)
    if start < 0 or end < start or end > length:
        raise error(f"Metadata segment ({start}, {end}) is outside a {length}-frame timeline.", segment_editor_config)
    if start == 0 and end == length:
        return {}
    if start == end:
        raise error("Metadata segment is empty.", segment_editor_config)
    remove: list[str] = []
    if start:
        remove.append("0" if start == 1 else f"0-{start - 1}")
    if end < length:
        remove.append(str(end) if end == length - 1 else f"{end}-{length - 1}")
    remove.reverse()
    return {"remove": remove}
