from . import utils, video, extension

from .utils import *
from .video import *

# TODO: Figure out something for the redefinition of modules here
from muxtools.main import *
from muxtools.audio import *  # type: ignore
from muxtools.muxing import *  # type: ignore
from muxtools.subtitle import *  # type: ignore
from muxtools.utils import *  # type: ignore

from .extension import *  # type: ignore

__version__: str
__version_tuple__: tuple[int | str, ...]

try:
    from ._version import __version__, __version_tuple__
except ImportError:
    __version__ = "0.0.0+unknown"
    __version_tuple__ = (0, 0, 0, "+unknown")
