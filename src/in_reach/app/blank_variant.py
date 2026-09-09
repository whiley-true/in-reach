"""Resolves this package's own bundled blank multiplayer/Firefight ``.bin`` templates.

PROMPT.md: a "New Blank Project" needs *something* to decompile/open in RVT with -- unlike the
built-in/personal flows, there's no existing ``.bin`` to point at, so in-reach ships its own
starting points (a bare multiplayer variant and a bare Firefight variant), same as
``in-reach-v1``'s own packaged ``blank_mp.bin``/``blank_ff.bin`` (see that repo's
``project_create.py::_copy_blank``). Resolved via :mod:`importlib.resources`, same pattern as
:mod:`in_reach.app.rvt_launcher`'s own bundled-executable lookup.
"""
from __future__ import annotations

from importlib import resources
from pathlib import Path

_PACKAGE = "in_reach.app"
_MULTIPLAYER_FILENAME = "blank_variants/blank_mp.bin"
_FIREFIGHT_FILENAME = "blank_variants/blank_ff.bin"


def resolve_blank_variant(*, firefight: bool) -> Path:
    """The bundled blank multiplayer (default) or Firefight ``.bin`` to start a blank project
    from.

    Args:
        firefight: ``True`` for the Firefight template, ``False`` for multiplayer.

    Returns:
        The template's path -- see :func:`~in_reach.app.rvt_launcher.resolve_rvt_exe`'s own
        docstring for why this stays valid past the ``with`` block for a normal (unzipped) install.
    """
    filename = _FIREFIGHT_FILENAME if firefight else _MULTIPLAYER_FILENAME
    resource = resources.files(_PACKAGE) / filename
    with resources.as_file(resource) as path:
        return path
