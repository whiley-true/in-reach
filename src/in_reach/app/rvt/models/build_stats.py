"""Space-usage and script content-count stats for a multiplayer game variant, mirroring
ReachVariantTool's own Script and Data Editor "Space usage" meter and per-metric counters
(ui/script_editor/bottom_bar.cpp). Built by in_reach.app.rvt.build_stats from the _reachvarianttool
binding backing it (MultiplayerData.get_full_size_data()) -- see that binding's docstring
(bindings.cpp) for why it's not just the C++-only get_size_data().

Ported near-verbatim from refactor/mide/models/build_stats.py.
"""
from pydantic import BaseModel


class SpaceUsageBits(BaseModel):
    """Per-section bit usage. Field names/values mirror ReachMPSizeData::bits (game_variants/
    types/multiplayer.h) exactly -- see that struct's own comments for what each section covers."""

    maximum: int
    header: int
    header_strings: int
    cg_options: int
    team_config: int
    script_traits: int
    script_options: int
    script_strings: int
    option_toggles: int
    rating_params: int
    map_perms: int
    script_content: int
    script_stats: int
    script_widgets: int
    forge_labels: int
    title_update_1: int


class ScriptContentCounts(BaseModel):
    """Entry counts. Field names mirror ReachMPSizeData::counts exactly."""

    triggers: int
    conditions: int
    actions: int
    forge_labels: int
    strings: int
    script_options: int
    script_stats: int
    script_traits: int
    script_widgets: int


class SpaceUsage(BaseModel):
    bits: SpaceUsageBits
    bytes_used: int  # ceil(total bits / 8) -- matches bottom_bar.cpp's own rounding
    bytes_max: int  # bits.maximum // 8 -- 0x5028 today (the MPVR block's capacity)
    percent: float


class BuildStats(BaseModel):
    space: SpaceUsage
    counts: ScriptContentCounts
