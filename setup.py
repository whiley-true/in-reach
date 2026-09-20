"""Setuptools configuration lives in ``pyproject.toml``; this exists for two things.

**The wheel tag.** The package ships a compiled extension (``in_reach/app/rvt/native/_reachvarianttool*.pyd``, built by
``native/build.py``) as package data rather than as a setuptools ``Extension``, so setuptools would call the wheel
pure-Python and tag it ``py3-none-any`` -- pip would then happily install a Windows-only binary on any platform and any
Python. Declaring that the distribution has extension modules makes it tag the wheel for the interpreter and platform it
was built on instead (e.g. ``cp314-cp314-win_amd64``).

**Only this Python's module.** ``native/build.py`` leaves the module it built in ``in_reach/app/rvt/native/``, one per
CPython version you have built for. A wheel is for one interpreter, so it must carry only that interpreter's
``_reachvarianttool.cpXYZ-*.pyd``: :func:`is_module_for_another_python` is what keeps the others (say, the cp312 one still
sitting there from an earlier build) out. The Qt runtime DLLs beside it are the same for every version and stay.

The source distribution carries no compiled files at all (``MANIFEST.in`` prunes that folder): it holds the C++ to build
them from.
"""

import re
import sys

from setuptools import setup
from setuptools.command.build_py import build_py as _build_py
from setuptools.dist import Distribution

_MODULE = re.compile(r"^_reachvarianttool\.cp(?P<tag>\d+)-")


def is_module_for_another_python(filename: str, version_info=None) -> bool:
    """Whether ``filename`` is a ``_reachvarianttool`` extension built for a CPython other than ``version_info`` (the
    running one by default). Anything else -- the DLLs, ``qt.conf``, any other file -- is not."""
    match = _MODULE.match(filename.replace("\\", "/").rsplit("/", 1)[-1])
    if match is None:
        return False
    version_info = version_info or sys.version_info
    return match["tag"] != f"{version_info.major}{version_info.minor}"


class BinaryDistribution(Distribution):
    def has_ext_modules(self) -> bool:
        return True


class build_py(_build_py):
    def find_data_files(self, package, src_dir):
        return [f for f in super().find_data_files(package, src_dir) if not is_module_for_another_python(f)]


if __name__ == "__main__":  # setuptools' build backend runs this file as __main__; importing it (the tests do) builds nothing
    setup(distclass=BinaryDistribution, cmdclass={"build_py": build_py})
