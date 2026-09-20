"""Checks that ``dist/`` holds exactly what a release should publish, before anything is uploaded to PyPI.

    python .github/scripts/check_dist.py dist --tag v0.3.0

Exits 0 if it does, otherwise prints every problem and exits 1. ``publish.yml`` runs it between collecting the
build artifacts and ``pypa/gh-action-pypi-publish``, because that action uploads whatever is in the folder and a
PyPI version can never be uploaded again: a wheel PyPI rejects (a ``linux_x86_64`` one, say -- what the old
Ubuntu-built wheel would now be tagged) after the sdist had gone up would leave a half-published release.

What it expects: one sdist, and one Windows wheel per Python in :data:`EXPECTED_PYTHONS` (each tagged for that
exact interpreter, ``cp312-cp312-win_amd64``, since the wheel carries a compiled module); every file for the
same version, and that version equal to the release tag if one is given; nothing else.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

#: The Pythons a release ships wheels for. ``.github/workflows/native.yml``'s matrix must list the same ones
#: (``tests/app/test_publish_workflow.py`` checks it does).
EXPECTED_PYTHONS = ("312", "313", "314")
PLATFORM = "win_amd64"
DISTRIBUTION = "in_reach"

_WHEEL = re.compile(r"^(?P<name>[^-]+)-(?P<version>[^-]+)-(?P<python>[^-]+)-(?P<abi>[^-]+)-(?P<platform>[^-]+)\.whl$")
_SDIST = re.compile(r"^(?P<name>[^-]+)-(?P<version>.+)\.tar\.gz$")


def problems(filenames: list[str], tag: str | None = None) -> list[str]:
    """Everything wrong with ``filenames`` (the names in ``dist/``) for a release; empty if it's fine."""
    found: list[str] = []
    versions: dict[str, str] = {}
    wheel_pythons: list[str] = []
    sdists: list[str] = []

    for name in sorted(filenames):
        wheel = _WHEEL.match(name)
        sdist = _SDIST.match(name)
        if wheel:
            if wheel["name"] != DISTRIBUTION:
                found.append(f"{name}: not a {DISTRIBUTION} wheel")
            if wheel["platform"] != PLATFORM:
                found.append(f"{name}: platform is {wheel['platform']!r}, not {PLATFORM!r} (PyPI would reject or mislabel it)")
            if not (wheel["python"].startswith("cp") and wheel["python"] == wheel["abi"]):
                found.append(f"{name}: python/abi tags {wheel['python']}-{wheel['abi']} aren't a matching cpXY pair")
            wheel_pythons.append(wheel["python"].removeprefix("cp"))
            versions[name] = wheel["version"]
        elif sdist:
            if sdist["name"] != DISTRIBUTION:
                found.append(f"{name}: not a {DISTRIBUTION} sdist")
            sdists.append(name)
            versions[name] = sdist["version"]
        else:
            found.append(f"{name}: not a wheel or an sdist")

    if len(sdists) != 1:
        found.append(f"expected exactly one sdist, found {len(sdists)}: {sdists}")

    missing = sorted(set(EXPECTED_PYTHONS) - set(wheel_pythons))
    extra = sorted(set(wheel_pythons) - set(EXPECTED_PYTHONS))
    repeated = sorted({p for p in wheel_pythons if wheel_pythons.count(p) > 1})
    if missing:
        found.append(f"no wheel for Python {', '.join(missing)}")
    if extra:
        found.append(f"unexpected wheel(s) for Python {', '.join(extra)}")
    if repeated:
        found.append(f"more than one wheel for Python {', '.join(repeated)}")

    if len(set(versions.values())) > 1:
        found.append(f"files disagree on the version: {sorted(set(versions.values()))}")
    if tag is not None:
        wanted = tag.removeprefix("v")
        wrong = sorted({v for v in versions.values() if v != wanted})
        if wrong:
            found.append(f"release tag {tag!r} is version {wanted}, but the files are {', '.join(wrong)}")
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("dist", type=Path, help="the folder to check")
    parser.add_argument("--tag", help="the release tag, e.g. v0.3.0; every file's version must match it")
    args = parser.parse_args(argv)

    if not args.dist.is_dir():
        print(f"{args.dist} is not a folder", file=sys.stderr)
        return 1
    names = [path.name for path in args.dist.iterdir() if path.is_file()]
    found = problems(names, args.tag)
    if found:
        print("Refusing to publish -- nothing was uploaded:", file=sys.stderr)
        for line in found:
            print(f"  - {line}", file=sys.stderr)
        return 1
    print(f"OK: {len(names)} files -- {', '.join(sorted(names))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
