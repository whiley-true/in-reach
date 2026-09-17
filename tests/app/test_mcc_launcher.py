from in_reach.app import mcc_launcher


def test_launch_mcc_opens_the_anti_cheat_disabled_steam_uri() -> None:
    seen = []

    mcc_launcher.launch_mcc(open_uri=seen.append)

    assert seen == [f"steam://launch/{mcc_launcher.MCC_STEAM_APP_ID}/option2"]
