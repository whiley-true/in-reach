from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from in_reach.app.categories import EngineCategory, EngineIcon
from in_reach.app.rvt.models.game_settings import Meta


def _meta(**overrides) -> dict:
    base = {"source_file": "x.bin", "generated_at": datetime.now(timezone.utc)}
    base.update(overrides)
    return base


def test_category_round_trips_through_dump_and_validate() -> None:
    meta = Meta(**_meta(category=EngineCategory.juggernaut, category_icon=EngineIcon.juggernaut))

    dumped = meta.model_dump(mode="json")
    assert dumped["category"] == "juggernaut"
    assert dumped["category_icon"] == "juggernaut"

    reloaded = Meta.model_validate(dumped)
    assert reloaded.category == EngineCategory.juggernaut
    assert reloaded.category_icon == EngineIcon.juggernaut


def test_category_accepts_the_enum_member_directly_too() -> None:
    meta = Meta.model_validate(_meta(category=EngineCategory.slayer))

    assert meta.category == EngineCategory.slayer


def test_category_icon_defaults_to_none_and_dumps_as_null() -> None:
    meta = Meta(**_meta())

    assert meta.category_icon is None
    assert meta.model_dump(mode="json")["category_icon"] is None


def test_an_unknown_category_name_raises_a_clean_validation_error_not_a_keyerror() -> None:
    # Regression guard: the "before" validator used to let a bare KeyError escape uncaught instead
    # of reporting it as a normal pydantic ValidationError.
    with pytest.raises(ValidationError, match="not a known category"):
        Meta.model_validate(_meta(category="not_a_real_category"))


def test_an_unknown_category_icon_name_raises_a_clean_validation_error() -> None:
    with pytest.raises(ValidationError, match="not a known category icon"):
        Meta.model_validate(_meta(category_icon="not_a_real_icon"))
