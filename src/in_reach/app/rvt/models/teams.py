"""ReachTeamData (game_variants/components/teams.h), edited on
ui/main_window/page_multiplayer_settings_team_specific.ui.
"""
from pydantic import BaseModel, Field


class Team(BaseModel):
    index: int = Field(ge=0, le=7)  # ReachCGTeamOptions::teams is a fixed 8-entry array
    name: str | None = Field(default=None, max_length=32)  # ReachStringTable(1, 0x20, ...) -- buffer is 0x20 = 32 bytes, confirmed 32 characters max
    enabled: bool = False
    color_primary_enabled: bool = False
    color_secondary_enabled: bool = False
    color_text_enabled: bool = False
    species: int = Field(default=0, ge=0, le=1)  # 0 = Spartan, 1 = Elite -- no registered py::enum_ for this field
    fireteam_count: int = Field(default=0, ge=0, le=31)
    initial_designator: int = Field(default=-1, ge=-1, le=8)  # -1 = None, 0-7 = Defenders(Red)..Team8(Pink), 8 = Neutral -- hardcoded list in page_multiplayer_settings_team_specific.cpp (_team_designators), not a reach:: enum
    color_primary: int = Field(default=0xFFFFFFFF, ge=0x00000000, le=0xFFFFFFFF)  # cobb::bytenumber<uint32_t> -- full 32-bit field; nominally xRGB (top byte unused) but the observed "unset" sentinel is 0xFFFFFFFF (all bits set), which doesn't fit a 24-bit range, so the constraint has to allow the full width
    color_secondary: int = Field(default=0xFFFFFFFF, ge=0x00000000, le=0xFFFFFFFF)  # same width/sentinel note as color_primary
    color_text: int = Field(default=0xFFFFFFFF, ge=0x00000000, le=0xFFFFFFFF)  # ARGB -- alpha channel is actually used here, unlike primary/secondary
