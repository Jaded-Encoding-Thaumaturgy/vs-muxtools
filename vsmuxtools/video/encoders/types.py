from enum import IntEnum
from typing import Union

__all__ = ["LosslessPreset", "ProResProfile"]

ZoneFrame = Union[int, None]
Zone = tuple[ZoneFrame, ZoneFrame, float | str] | tuple[ZoneFrame, ZoneFrame, str, float | int | str]


class LosslessPreset(IntEnum):
    SPEED = 1
    COMPRESSION = 2
    MIDDLEGROUND = 3


class ProResProfile(IntEnum):
    AUTO = -1
    PROXY = 0
    LT = 1
    DEFAULT = 2
    HQ = 3
    P4444 = 4
    P4444XQ = 5
