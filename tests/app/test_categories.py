from in_reach.app.categories import EngineCategory, EngineIcon, default_icon_for, display_name, mismatch_warning


def test_display_name_titles_the_underscored_member_name() -> None:
    assert display_name(EngineCategory.king_of_the_hill) == "King Of The Hill"


def test_display_name_of_none_category_reads_as_none_forge() -> None:
    assert display_name(EngineCategory.none) == "None (Forge)"


def test_default_icon_for_none_category_is_none() -> None:
    assert default_icon_for(EngineCategory.none) is None


def test_default_icon_for_a_plain_category_matches_by_name() -> None:
    assert default_icon_for(EngineCategory.slayer) == EngineIcon.slayer
    assert default_icon_for(EngineCategory.oddball) == EngineIcon.oddball


def test_default_icon_for_the_two_renamed_categories() -> None:
    # EngineCategory and EngineIcon spell these two the same real gametype differently.
    assert default_icon_for(EngineCategory.unknown_vip) == EngineIcon.vip
    assert default_icon_for(EngineCategory.race) == EngineIcon.race_and_rally


def test_mismatch_warning_is_none_when_they_correspond() -> None:
    assert mismatch_warning(EngineCategory.slayer, EngineIcon.slayer) is None
    assert mismatch_warning(EngineCategory.race, EngineIcon.race_and_rally) is None


def test_mismatch_warning_is_none_for_the_none_category_regardless_of_icon() -> None:
    assert mismatch_warning(EngineCategory.none, EngineIcon.crosshair) is None


def test_mismatch_warning_names_both_when_they_do_not_correspond() -> None:
    warning = mismatch_warning(EngineCategory.slayer, EngineIcon.oddball)

    assert warning is not None
    assert "Slayer" in warning
    assert "Oddball" in warning


def test_mismatch_warning_flags_a_purely_decorative_icon_too() -> None:
    warning = mismatch_warning(EngineCategory.slayer, EngineIcon.crosshair)

    assert warning is not None
