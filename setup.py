"""Setuptools configuration lives in ``pyproject.toml``; this exists for one thing.

The package ships a compiled extension (``in_reach/app/rvt/native/_reachvarianttool*.pyd``, built by
``native/build.py``) as package data rather than as a setuptools ``Extension``, so setuptools would call the
wheel pure-Python and tag it ``py3-none-any`` -- pip would then happily install a Windows-only binary on any
platform and any Python. Declaring that the distribution has extension modules makes it tag the wheel for the
interpreter and platform it was built on instead (e.g. ``cp314-cp314-win_amd64``).

The source distribution is unaffected, and a wheel built where nothing was compiled (say, an editable install
on Linux for the pure-Python parts) is simply tagged for that machine.
"""

from setuptools import setup
from setuptools.dist import Distribution


class BinaryDistribution(Distribution):
    def has_ext_modules(self) -> bool:
        return True


setup(distclass=BinaryDistribution)
