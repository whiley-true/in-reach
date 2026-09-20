"""The design's own worked example ("Hill Rush", ``TO_IMPLEMENT`` §13) as files, shared by the script-project tests
that need a whole project on disk. Not a test module."""
from pathlib import Path

PROJECT_TOML = """[project]
name = "hill_rush"
profile = "dev"

[constants]
SCORE_INTERVAL = 1
SCORE_TO_WIN = 50

[blocks]
order = ["SETUP", "HILL_PASS", "WIN_CHECK"]

[[modules]]
name = "hill_score"

[[modules]]
name = "hill_buff"

[kinds.hill]
reached_by = ["label:hill"]
"""

HILL = {
    "project.toml": PROJECT_TOML,
    "env/dev.env": "FLAGS=DEV\nSCORE_TO_WIN=5\n",
    "blocks/setup.mgl": "-- @number g_phase priority=low\non init: do\n   g_phase = 0\nend\n",
    "blocks/win_check.mgl": "-- @doc ends the game\nif global.number[0] == ${SCORE_TO_WIN} then\n   game.end_round()\nend\n",
    "modules/hill_score/module.toml": (
        '[module]\nname = "hill_score"\nversion = "1.0.0"\n\n[order]\nafter = ["SETUP"]\n\n'
        '[params]\nscore_interval = { type = "number", default = "${SCORE_INTERVAL}" }\n\n'
        '[kinds]\nhill = { reached_by = ["label:hill"] }\n'
    ),
    "modules/hill_score/hill_score.mgl": (
        "-- @ptimer p_hill_timer default=${score_interval}\n-- @fragment HILL_PASS.score\n-- @loop player\nx = 1\n"
    ),
    "modules/hill_buff/module.toml": '[module]\nname = "hill_buff"\n\n[order]\nafter = ["SETUP"]\n',
    "modules/hill_buff/hill_buff.mgl": (
        '-- @trait t_hill_buff { movement_speed = "value_120" }\n-- @fragment HILL_PASS.buff\n-- @loop player\n'
        "-- @if DEV\ny = 1\n-- @end\n"
    ),
}


def write_project(folder: Path, files: dict[str, str | None]) -> Path:
    """Writes ``files`` (paths relative to ``folder/script``; a ``None`` value leaves that file out)."""
    for relative, text in files.items():
        if text is None:
            continue
        path = folder / "script" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return folder


def hill_rush(folder: Path, **replace: str | None) -> Path:
    """The example project in ``folder``, with the files named in ``replace`` (``/`` written ``__``, ``.`` written
    ``_dot_``) changed or, for a ``None`` value, left out."""
    files = dict(HILL)
    for key, value in replace.items():
        files[key.replace("__", "/").replace("_dot_", ".").replace("_dash_", "-")] = value
    return write_project(folder, files)
