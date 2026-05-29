import random
from muxtools import PathLike, ensure_path

__all__ = [
    "SVTAV1_LIGHT_NOISE_TABLE_FULL",
    "SVTAV1_LIGHT_NOISE_TABLE_LIMITED",
    "x265_write_light_noise_table_limited",
    "x265_write_light_noise_table_full",
]

SVTAV1_LIGHT_NOISE_TABLE_LIMITED = """filmgrn1
E 0 18446744073709551615 1 787 1
	p 3 7 0 8 0 1 128 192 256 128 192 256
    sY 9 0 0 16 0 17 2 18 3 157 3 177 4 233 4 235 0 255 0
	sCb 0
	sCr 0
	cY 3 4 3 3 3 3 3 3 4 2 0 2 3 3 3 2 -7 -19 -4 1 3 2 0 -18
	cCb -3 9 -15 20 -6 0 0 9 -22 32 -50 10 -3 1 -15 32 -61 70 -26 -1 -2 17 -40 59 11
	cCr -3 9 -15 20 -6 0 1 9 -21 32 -50 10 -3 0 -14 31 -61 71 -26 -1 -1 17 -40 58 11
"""
"""
A table for photon noise that serves as a light dither layer to prevent banding.\n
With cutoffs for limited range clips.
"""

SVTAV1_LIGHT_NOISE_TABLE_FULL = """filmgrn1
E 0 18446744073709551615 1 787 1
	p 3 7 0 8 0 1 128 192 256 128 192 256
	sY 6 0 4 20 3 157 3 177 4 235 4 255 5
	sCb 0
	sCr 0
	cY 3 4 3 3 3 3 3 3 4 2 0 2 3 3 3 2 -7 -19 -4 1 3 2 0 -18
	cCb -3 9 -15 20 -6 0 0 9 -22 32 -50 10 -3 1 -15 32 -61 70 -26 -1 -2 17 -40 59 11
	cCr -3 9 -15 20 -6 0 1 9 -21 32 -50 10 -3 0 -14 31 -61 71 -26 -1 -1 17 -40 58 11
"""
"""
A table for photon noise that serves as a light dither layer to prevent banding.\n
With cutoffs for full range clips.
"""


def x265_write_light_noise_table_helper(target: PathLike, length: int, s: str):
    # fmt: off
    seed_pool = [65506, 65501, 65484, 65476, 65466, 65464, 65420, 65417, 65391, 65345, 65333, 65299,
                65260, 64921, 64917, 64831, 64774, 64693, 64448, 64436, 64435, 64423, 64384, 64332,
                64285, 64274, 64240, 64189, 64176, 64126, 64113, 64093, 63947, 63647, 63580, 63507,
                63504, 63456, 63023, 62518, 62359, 62258, 62156, 62143, 62040, 61851, 61692, 61482,
                61476, 60973, 60878, 60711, 60619, 60584, 60537, 60501, 60123, 59991, 59929, 59846,
                59724, 59669, 59665, 59637, 59625, 59621, 59180, 59119]
    # fmt: on
    seeds = [63504]
    while len(seeds) < length:
        n = random.choice(seed_pool)
        if n not in seeds[-32:]:
            seeds.append(n)

    with ensure_path(target, None).open("wb") as f:
        for seed in seeds:
            f.write((1).to_bytes(4, byteorder="little", signed=True))
            f.write((seed).to_bytes(2, byteorder="little", signed=False))
            f.write((1).to_bytes(4, byteorder="little", signed=True))

            for n in s.split():
                f.write((int(n)).to_bytes(4, byteorder="little", signed=True))
            f.write((0).to_bytes(4, byteorder="little", signed=True))
            f.write((0).to_bytes(4, byteorder="little", signed=True))
            f.write((8).to_bytes(4, byteorder="little", signed=True))

            f.write((3).to_bytes(4, byteorder="little", signed=True))
            for n in "3 4 3 3 3 3 3 3 4 2 0 2 3 3 3 2 -7 -19 -4 1 3 2 0 -18".split():
                f.write((int(n)).to_bytes(4, byteorder="little", signed=True))
            f.write((7).to_bytes(4, byteorder="little", signed=True))
            f.write((0).to_bytes(4, byteorder="little", signed=True))

            f.write((1).to_bytes(4, byteorder="little", signed=True))
            f.write((1).to_bytes(4, byteorder="little", signed=True))


def x265_write_light_noise_table_limited(target: PathLike, length: int):
    """
    A table for photon noise that serves as a light dither layer to prevent banding.\n
    With cutoffs for limited range clips.
    """
    x265_write_light_noise_table_helper(target, length, "9 0 0 16 0 17 2 18 3 157 3 177 4 233 4 235 0 255 0")


def x265_write_light_noise_table_full(target: PathLike, length: int):
    """
    A table for photon noise that serves as a light dither layer to prevent banding.\n
    With cutoffs for full range clips.
    """
    x265_write_light_noise_table_helper(target, length, "6 0 4 20 3 157 3 177 4 235 4 255 5")
