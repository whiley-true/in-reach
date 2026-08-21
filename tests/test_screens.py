import json

from inreach.app.setup import screens


def test_save_screen_config_writes_json(tmp_path):
    fake_screens = [
        {"device": "\\\\.\\DISPLAY1", "x": 0, "y": 0, "width": 2560, "height": 1440, "primary": True},
        {"device": "\\\\.\\DISPLAY2", "x": -1920, "y": 0, "width": 1920, "height": 1080, "primary": False},
    ]

    config_path = screens.save_screen_config(tmp_path, screens=fake_screens)

    assert config_path == tmp_path / "config" / "screens.json"
    assert json.loads(config_path.read_text(encoding="utf-8")) == fake_screens
