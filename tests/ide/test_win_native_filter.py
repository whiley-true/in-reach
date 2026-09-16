import ctypes
from ctypes import wintypes

import pytest

from in_reach.ide.win_native_filter import WM_GETOBJECT, BlockAccessibilityQueries


def _msg_address(message: int) -> int:
    msg = wintypes.MSG()
    msg.message = message
    # Kept alive by the caller for as long as the address is used -- ctypes doesn't pin memory on
    # its own once the local goes out of scope.
    _msg_address.keepalive = msg  # type: ignore[attr-defined]
    return ctypes.addressof(msg)


@pytest.fixture(autouse=True)
def _windows_platform(monkeypatch):
    monkeypatch.setattr("in_reach.ide.win_native_filter.sys.platform", "win32")


def test_swallows_wm_getobject():
    result, code = BlockAccessibilityQueries().nativeEventFilter(
        b"windows_generic_MSG", _msg_address(WM_GETOBJECT)
    )
    assert result is True
    assert code == 0


def test_lets_other_messages_through():
    result, _code = BlockAccessibilityQueries().nativeEventFilter(
        b"windows_generic_MSG", _msg_address(WM_GETOBJECT + 1)
    )
    assert result is False


def test_ignores_non_windows_event_types():
    result, _code = BlockAccessibilityQueries().nativeEventFilter(
        b"some_other_MSG", _msg_address(WM_GETOBJECT)
    )
    assert result is False


def test_never_intercepts_off_windows(monkeypatch):
    monkeypatch.setattr("in_reach.ide.win_native_filter.sys.platform", "linux")
    result, _code = BlockAccessibilityQueries().nativeEventFilter(
        b"windows_generic_MSG", _msg_address(WM_GETOBJECT)
    )
    assert result is False
