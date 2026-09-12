"""Shared state that can be reused by every casino table."""
from dataclasses import dataclass


@dataclass
class PlayerState:
    chips: int = 200
