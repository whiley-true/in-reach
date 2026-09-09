"""Build stats (space usage + trigger/condition/action/etc. counts) for a multiplayer game
variant. Mirrors what ReachVariantTool's own Script and Data Editor "Space usage" meter
(ui/script_editor/bottom_bar.cpp) shows in the GUI, built off the
MultiplayerData.get_full_size_data() binding -- already exposed on the shipped
_reachvarianttool.pyd, confirmed live against tests/app/rvt/resources/juggernaut/juggernaut.bin.

Ported near-verbatim from ``in-reach-v1``'s own ``rvt/build_stats.py``.
"""

from .models.build_stats import BuildStats, ScriptContentCounts, SpaceUsage, SpaceUsageBits


def build_stats_from_multiplayer(mp) -> BuildStats:
    data = mp.get_full_size_data()
    bits = SpaceUsageBits(**data.bits)
    total_bits = data.total_bits()
    # Matches bottom_bar.cpp's own final block exactly: bytes_max is a floor division (the meter's
    # own maximum is always a whole number of bytes), bytes_used is a ceil division (any partial
    # byte still costs a full byte on disk).
    bytes_max = bits.maximum // 8
    bytes_used = (total_bits + 7) // 8
    percent = (total_bits / bits.maximum * 100) if bits.maximum else 0.0
    return BuildStats(
        space=SpaceUsage(bits=bits, bytes_used=bytes_used, bytes_max=bytes_max, percent=percent),
        counts=ScriptContentCounts(**data.counts),
    )
