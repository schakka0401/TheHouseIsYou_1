"""Shared state that can be reused by every casino table."""
from dataclasses import dataclass


STARTING_BANKROLL = 200


@dataclass
class PlayerState:
    chips: int = STARTING_BANKROLL


def ensure_playable_bankroll(player_state: PlayerState) -> None:
    """Restore only an empty/depleted bankroll before starting a table game."""
    if player_state.chips <= 0:
        player_state.chips = STARTING_BANKROLL
