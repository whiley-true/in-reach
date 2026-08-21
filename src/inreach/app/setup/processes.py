"""Injectable wrappers over ``tasklist``/``taskkill`` for checking and
closing Windows processes by executable name.

Every function takes its subprocess/sleep dependency as a keyword
argument with a real default, so tests can inject fakes and never spawn
real processes.
"""

import logging
import subprocess
import time

logger = logging.getLogger(__name__)


def is_process_running(exe_name: str, run=subprocess.run) -> bool:
    result = run(
        ["tasklist", "/FI", f"IMAGENAME eq {exe_name}", "/NH"],
        capture_output=True,
        text=True,
    )
    return exe_name.lower() in result.stdout.lower()


def close_process(exe_name: str, run=subprocess.run) -> None:
    logger.info("Closing process %s", exe_name)
    run(["taskkill", "/IM", exe_name, "/F"], capture_output=True, text=True)


def wait_for_process(
    exe_name: str,
    timeout: float,
    poll_interval: float = 1.0,
    is_running=is_process_running,
    sleep=time.sleep,
) -> bool:
    """Poll for ``exe_name`` to appear in the process list.

    Returns ``True`` as soon as it's seen running, ``False`` if it never
    shows up within ``timeout`` seconds.
    """
    elapsed = 0.0
    while elapsed <= timeout:
        if is_running(exe_name):
            return True
        sleep(poll_interval)
        elapsed += poll_interval
    return False
