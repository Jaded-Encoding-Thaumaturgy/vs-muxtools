from enum import Enum

__all__ = ["LosslessPreset"]

Zone = tuple[int, int, float | str] | tuple[int, int, str, float | int | str]


class LosslessPreset(Enum):
    SPEED = 1
    COMPRESSION = 2
    MIDDLEGROUND = 3
