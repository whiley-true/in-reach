from inreach.app.setup import processes


class _FakeResult:
    def __init__(self, stdout):
        self.stdout = stdout


def test_is_process_running_true_when_listed():
    def fake_run(cmd, **kwargs):
        return _FakeResult("Image Name\nsteam.exe   1234\n")

    assert processes.is_process_running("steam.exe", run=fake_run) is True


def test_is_process_running_false_when_not_listed():
    def fake_run(cmd, **kwargs):
        return _FakeResult("INFO: No tasks are running which match the specified criteria.")

    assert processes.is_process_running("steam.exe", run=fake_run) is False


def test_close_process_invokes_taskkill():
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return _FakeResult("")

    processes.close_process("steam.exe", run=fake_run)

    assert calls == [["taskkill", "/IM", "steam.exe", "/F"]]


def test_wait_for_process_returns_true_once_running():
    states = [False, False, True]

    def fake_is_running(name):
        return states.pop(0)

    sleeps = []

    processes.wait_for_process(
        "mcc.exe", timeout=10, poll_interval=1, is_running=fake_is_running, sleep=sleeps.append
    )

    assert sleeps == [1, 1]


def test_wait_for_process_times_out():
    result = processes.wait_for_process(
        "mcc.exe", timeout=2, poll_interval=1, is_running=lambda name: False, sleep=lambda s: None
    )

    assert result is False
