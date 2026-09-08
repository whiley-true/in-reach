"""Loads the compiled `_reachvarianttool` pybind11 extension module on demand.

The module (plus the Qt/zlib DLLs it loads) ships as a prebuilt binary inside this package's own
``native/`` folder (see that folder's own place in package-data in pyproject.toml) -- resolved via
:func:`importlib.resources` rather than a path built off ``__file__``, same reasoning as
``in_reach.app.project``'s template lookup: it keeps working whether in-reach is run from a source
checkout or a pip-installed package.
"""
from __future__ import annotations

import contextlib
import os
import sys
from importlib import resources

_RVT_PACKAGE = "in_reach.app.rvt"
_NATIVE_DIRNAME = "native"

# The real OS-level stdout file descriptor -- deliberately *not* `sys.stdout.fileno()`, see
# _suppress_native_stdout()'s docstring for why that's the wrong thing to redirect.
_STDOUT_FD = 1

_module = None


@contextlib.contextmanager
def _suppress_native_stdout():
    """Redirects OS file descriptor 1 (stdout) to `os.devnull` for the duration of the with-block.

    Some `.bin`s (built-in variants in particular -- see `rvt.load()`'s own diagnostic) make the
    native module print a line like "Loaded a game variant with isBuiltIn set to (true)..."
    straight to the C stdout stream (printf/std::cout), bypassing Python's `sys.stdout` object
    entirely -- reassigning `sys.stdout` or monkeypatching `print()` can't catch that, only a real
    file-descriptor-level redirect can.

    Redirects the literal fd `1`, not `sys.stdout.fileno()` -- the C runtime's stdout stream (what
    printf/std::cout actually write to) is bound to the real fd `1` at process startup, independent
    of whatever `sys.stdout` has been reassigned to at the Python level. Under pytest's own `capfd`
    fixture in particular, `sys.stdout.fileno()` returns a *different* fd (its own capture temp
    file) -- redirecting that would silently miss the real fd `1` writes entirely, which is exactly
    the bug an earlier version of this function had.

    Falls back to doing nothing if the fd-level redirect itself fails for any reason (e.g. a
    sandboxed environment where dup/dup2 aren't permitted) rather than raising -- suppressing this
    noise is a nicety, not something worth failing a real command over.
    """
    try:
        saved_fd = os.dup(_STDOUT_FD)
    except OSError:
        yield
        return

    try:
        devnull_fd = os.open(os.devnull, os.O_WRONLY)
        try:
            os.dup2(devnull_fd, _STDOUT_FD)
            yield
        finally:
            os.dup2(saved_fd, _STDOUT_FD)
            os.close(devnull_fd)
    finally:
        os.close(saved_fd)


def get_rvt():
    global _module
    if _module is None:
        native_dir = resources.files(_RVT_PACKAGE) / _NATIVE_DIRNAME
        with resources.as_file(native_dir) as native_path:
            build_dir = str(native_path)
            if build_dir not in sys.path:
                sys.path.insert(0, build_dir)
            import _reachvarianttool as rvt

        # Every caller loads a .bin through this same entry point, so wrapping it once here (rather
        # than at each of cli.py/init_m.py/compile.py/browse.py's own rvt.load() call sites) is the
        # one place that reliably filters _suppress_native_stdout()'s target message everywhere,
        # present and future.
        native_load = rvt.load

        def _load(path):
            with _suppress_native_stdout():
                return native_load(path)

        rvt.load = _load
        _module = rvt
    return _module
