import pathlib

USERS_DIR = pathlib.Path("C:/Users")

_EXCLUDED_NAMES = {"public", "default", "default user", "all users"}


def list_windows_users(users_dir: pathlib.Path = USERS_DIR) -> list[str]:
    """Return the user folder names under ``users_dir``, minus system entries."""
    if not users_dir.exists():
        return []

    names = []
    for entry in sorted(users_dir.iterdir()):
        if entry.name.lower() in _EXCLUDED_NAMES or entry.name.startswith("."):
            continue
        try:
            if entry.is_dir():
                names.append(entry.name)
        except OSError:
            continue
    return names
