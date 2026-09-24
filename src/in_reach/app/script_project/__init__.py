"""A script project: ``script/project.toml``, its modules and block files, loaded and checked.

::

    from in_reach.app.script_project import is_linked, load_project

    if is_linked(folder):                # a script/project.toml exists
        project = load_project(folder)   # never raises for a problem in the project's files
        for diagnostic in project.diagnostics:
            print(diagnostic)            # "modules/hill_buff/module.toml:5: error: ... [order-unknown-block]"

Nothing here loads the native extension or Qt, so the IDE process can import it (``link`` builds ``build/Compiled.txt``
from the project -- or from a single ``script/output.mgl``, as a project of one block (:func:`load_single_file`); the
compile flow calls it before compiling). See :mod:`.project` for what is
loaded and reported, and ``TO_IMPLEMENT`` §2 and §5 for the layout it reads.
"""

from .diagnostics import ProjectDiagnostic
from .linker import LinkResult, link, read_link_map, record_counters
from .scaffold import create_module, create_project
from .project import LoadedBlock, LoadedModule, MergedKind, ScriptProject, SourceFile, is_linked, load_project, load_script, load_single_file

__all__ = [
    "LinkResult",
    "LoadedBlock",
    "LoadedModule",
    "MergedKind",
    "ProjectDiagnostic",
    "ScriptProject",
    "SourceFile",
    "create_module",
    "create_project",
    "is_linked",
    "link",
    "read_link_map",
    "record_counters",
    "load_project",
    "load_script",
    "load_single_file",
]
