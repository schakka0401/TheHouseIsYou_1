"""Local Poker dealer voice and portrait presentation."""
from __future__ import annotations

from pathlib import Path
import random

import pygame

from game.dealer_voice import DealerVoiceManager, DealerVoicePriority


POKER_DEALER_LINES = (
    "poker_intro",
    "poker_round_1",
    "poker_round_2",
    "poker_round_3",
    "poker_reaction_1",
    "poker_reaction_2",
    "poker_reaction_3",
    "poker_reaction_4",
    "poker_final_round",
    "poker_results",
)

PORTRAIT_FOR_LINE = {
    "poker_intro": "poker_neutral",
    "poker_round_1": "poker_neutral",
    "poker_round_2": "poker_contemplative",
    "poker_round_3": "poker_contemplative",
    "poker_reaction_1": "poker_contemplative",
    "poker_reaction_2": "poker_neutral",
    "poker_reaction_3": "poker_contemplative",
    "poker_reaction_4": "poker_contemplative",
    "poker_final_round": "poker_contemplative",
    "poker_results": "poker_neutral",
}

POKER_DEALER_PORTRAITS = tuple(sorted(set(PORTRAIT_FOR_LINE.values())))
PORTRAIT_HIDE_DELAY_MS = 220
POKER_DEALER_VOICE_DIRECTORY = (
    Path(__file__).resolve().parents[1] / "static" / "assets" / "audio" / "poker_voicelines"
)
POKER_DEALER_PORTRAIT_DIRECTORY = (
    Path(__file__).resolve().parents[1] / "static" / "assets" / "images" / "dealers"
)
DEBUG_POKER_DEALER = False


class PokerDealerOverlay:
    """Coordinates one Poker voice manager with its temporary portrait."""

    def __init__(self, screen: pygame.Surface, audio_manager=None, seed: int | None = None) -> None:
        self.screen = screen
        self.random = random.Random(seed)
        self.voice = (
            DealerVoiceManager(
                audio_manager,
                voice_directory=POKER_DEALER_VOICE_DIRECTORY,
                line_names=POKER_DEALER_LINES,
                debug=DEBUG_POKER_DEALER,
            )
            if audio_manager is not None
            else None
        )
        self.portraits: dict[str, pygame.Surface] = {}
        self.scaled_portraits: dict[tuple[str, tuple[int, int]], pygame.Surface] = {}
        self._load_portraits()
        self.active_portrait: str | None = None
        self.active_voice: str | None = None
        self.dealer_visible = False
        self.dealer_speaking = False
        self.hide_at: int | None = None

    def _debug(self, message: str) -> None:
        if DEBUG_POKER_DEALER:
            print(f"[POKER DEALER] {message}")

    def _load_portraits(self) -> None:
        for name in POKER_DEALER_PORTRAITS:
            matches = sorted(POKER_DEALER_PORTRAIT_DIRECTORY.glob(f"{name}.*"))
            if not matches:
                self._debug(f"missing portrait: {name}")
                continue
            try:
                self.portraits[name] = pygame.image.load(matches[0]).convert_alpha()
            except (pygame.error, OSError) as error:
                self._debug(f"could not load {matches[0].name}: {error}")

    def _show_for_current_voice(self) -> None:
        if self.voice is None or self.voice.current is None:
            return
        name = self.voice.current.name
        portrait = PORTRAIT_FOR_LINE.get(name)
        if portrait is None or portrait not in self.portraits:
            return
        self.active_voice = name
        self.active_portrait = portrait
        self.dealer_visible = True
        self.hide_at = None
        self._debug(f"portrait shown {portrait} for {name}")

    def play_line(
        self,
        name: str,
        priority: DealerVoicePriority,
        *,
        context: str | None = None,
    ) -> str:
        if self.voice is None:
            return "dropped"
        outcome = self.voice.play_dealer_line(name, priority, context=context)
        if outcome == "played":
            self._show_for_current_voice()
        return outcome

    def clear_context(
        self,
        context: str,
        *,
        include_high: bool = False,
        stop_current: bool = False,
    ) -> None:
        if self.voice is not None:
            self.voice.clear_stale_dealer_lines(
                context,
                include_high=include_high,
                stop_current=stop_current,
            )
        if stop_current:
            self.hide_at = pygame.time.get_ticks()

    def reset(self) -> None:
        if self.voice is not None:
            self.voice.shutdown()
        self.active_portrait = None
        self.active_voice = None
        self.dealer_visible = False
        self.dealer_speaking = False
        self.hide_at = None
        self._debug("portrait/audio state reset")

    def update(self) -> None:
        now = pygame.time.get_ticks()
        was_speaking = self.dealer_speaking
        if self.voice is not None:
            self.voice.update_dealer_voice()
        current = self.voice.current if self.voice is not None else None
        self.dealer_speaking = bool(current and self.voice and self.voice.is_dealer_speaking())

        if current is not None:
            if current.name != self.active_voice:
                self._show_for_current_voice()
            return
        if was_speaking and self.dealer_visible:
            self.hide_at = now + PORTRAIT_HIDE_DELAY_MS
            self._debug(f"voice finished {self.active_voice}; portrait hide scheduled")
        if self.hide_at is not None and now >= self.hide_at:
            self._debug(f"portrait hidden {self.active_portrait}")
            self.active_portrait = None
            self.active_voice = None
            self.dealer_visible = False
            self.hide_at = None

    def _display_surface(self) -> tuple[pygame.Surface, pygame.Rect] | None:
        if not self.dealer_visible or self.active_portrait is None:
            return None
        source = self.portraits.get(self.active_portrait)
        if source is None:
            return None
        cache_key = (self.active_portrait, self.screen.get_size())
        surface = self.scaled_portraits.get(cache_key)
        if surface is None:
            max_height = max(1, min(120, int(self.screen.get_height() * 0.15)))
            scale = min(1.0, max_height / source.get_height())
            size = (
                max(1, int(source.get_width() * scale)),
                max(1, int(source.get_height() * scale)),
            )
            surface = pygame.transform.smoothscale(source, size)
            self.scaled_portraits[cache_key] = surface
        # Keep the small portrait in the upper-right margin, above the player
        # rows and outside the centered results paper.
        rect = surface.get_rect(topright=(self.screen.get_width() - 18, 42))
        return surface, rect

    def draw(self) -> None:
        displayed = self._display_surface()
        if displayed is None:
            return
        surface, rect = displayed
        self.screen.blit(surface, rect)
