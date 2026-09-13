"""The live, in-process indent style/width every open :class:`~in_reach.ide.editor.TextEditorWidget`
reads from its own ``Tab`` key handling.

Module-level state, same convention as :mod:`in_reach.ide.zoom`'s own ``_base_font`` -- there's only
ever one running IDE process to track this for, and threading a project path through every editor
just to re-read :mod:`in_reach.app.indent_settings` on every keystroke would be needless I/O.
:class:`~in_reach.ide.main_window.MainWindow` calls :func:`set` once at startup (seeded from the
persisted value) and again whenever a Quick Access Bar indentation command changes it.
"""

from __future__ import annotations

from in_reach.app import indent_settings

_style = indent_settings.DEFAULT_INDENT_STYLE
_width = indent_settings.DEFAULT_INDENT_WIDTH


def get_indent() -> tuple[str, int]:
    """The live ``(style, width)`` -- :data:`~in_reach.app.indent_settings.DEFAULT_INDENT_STYLE`/
    :data:`~in_reach.app.indent_settings.DEFAULT_INDENT_WIDTH` until :func:`set_indent` is first
    called."""
    return _style, _width


def set_indent(style: str, width: int) -> None:
    """Updates the live indent style/width -- does not itself persist anything, see
    :func:`in_reach.app.indent_settings.set_indent` for that."""
    global _style, _width
    _style = style
    _width = width
