"""Shared input and editor types for dynamic HDR metadata helpers."""

from collections.abc import Sequence
from typing import Literal, TypedDict

from muxtools import Trim


type JSONValue = str | int | float | bool | None | list[JSONValue] | dict[str, JSONValue]


class DuplicateConfig(TypedDict):
    source: int
    offset: int
    length: int


class TimelineConfig(TypedDict, total=False):
    remove: list[str]
    duplicate: list[DuplicateConfig]


type MetadataOperation = (
    tuple[Literal["trim", "remove"], Trim | list[int | None] | Sequence[Trim] | None]
    | tuple[Literal["duplicate"], tuple[int, int]]
    | tuple[Literal["config"], dict[str, JSONValue]]
    | tuple[Literal["crop"], Trim | list[int | None] | Sequence[Trim]]
    | tuple[Literal["active_area"], tuple[tuple[int, int, int, int], Trim | list[int | None] | Sequence[Trim] | None]]
)
