"""Centralized music and footstep audio for the menu and casino world."""
from __future__ import annotations

from pathlib import Path

import pygame

MUSIC_VOLUME = 0.50
FOOTSTEP_VOLUME = 0.78
FOOTSTEP_INTERVAL_MS = 320


class AudioManager:
    def __init__(self) -> None:
        self.audio_dir = Path(__file__).resolve().parents[1] / "static" / "assets" / "audio"
        self.available = False
        self.music_volume = MUSIC_VOLUME
        self.sfx_volume = 0.50
        self._registered_sounds: list[tuple[pygame.mixer.Sound, float]] = []
        self.current_music: str | None = None
        self.steps: list[pygame.mixer.Sound] = []
        self.footstep_channel = None
        self.ui_channel = None
        self.interaction_channel = None
        self.interaction_sounds: dict[str, pygame.mixer.Sound] = {}
        try:
            if pygame.mixer.get_init() is None:
                pygame.mixer.init()
            self.available = True
            # Keep world footsteps, UI feedback, and NPC interaction audio on
            # channels which cannot be borrowed by Sound.play(). This lets
            # button hover sounds play without cutting off dealer dialogue.
            pygame.mixer.set_reserved(3)
            self.footstep_channel = pygame.mixer.Channel(0)
            self.ui_channel = pygame.mixer.Channel(1)
            self.interaction_channel = pygame.mixer.Channel(2)
            self.steps = [self._load_sound("step0"), self._load_sound("step1")]
            for sound in self.steps:
                self.register_sound(sound, FOOTSTEP_VOLUME)
            for name in ("bartender_interact", "poker_interact", "blackjack_interact"):
                try:
                    sound = self._load_sound(name)
                except (pygame.error, FileNotFoundError):
                    continue
                self.interaction_sounds[name] = sound
                self.register_sound(sound, 0.85)
        except (pygame.error, FileNotFoundError):
            self.available = False
            self.steps = []

    def _find_asset(self, stem: str) -> Path:
        matches = sorted(self.audio_dir.glob(f"{stem}.*"))
        if not matches:
            raise FileNotFoundError(f"Missing audio asset: {self.audio_dir / stem}.*")
        return matches[0]

    def _load_sound(self, stem: str) -> pygame.mixer.Sound:
        return pygame.mixer.Sound(str(self._find_asset(stem)))

    def register_sound(self, sound: pygame.mixer.Sound, base_volume: float) -> None:
        self._registered_sounds.append((sound, base_volume))
        sound.set_volume(base_volume * self.sfx_volume)

    def set_music_volume(self, value: float) -> None:
        self.music_volume = max(0.0, min(1.0, value))
        if self.available:
            pygame.mixer.music.set_volume(self.music_volume)

    def set_sfx_volume(self, value: float) -> None:
        self.sfx_volume = max(0.0, min(1.0, value))
        for sound, base_volume in self._registered_sounds:
            sound.set_volume(base_volume * self.sfx_volume)

    def play_music(self, track: str) -> None:
        if not self.available:
            return
        if self.current_music == track and pygame.mixer.music.get_busy():
            return
        path = self._find_asset(track)
        if self.current_music is not None and self.current_music != track:
            pygame.mixer.music.fadeout(350)
        pygame.mixer.music.load(str(path))
        pygame.mixer.music.set_volume(self.music_volume)
        pygame.mixer.music.play(-1)
        self.current_music = track

    def stop_music(self, fade_ms: int = 350) -> None:
        if not self.available:
            return
        if pygame.mixer.music.get_busy():
            pygame.mixer.music.fadeout(fade_ms)
        self.current_music = None

    def play_step(self, index: int) -> None:
        if self.available and self.steps and self.footstep_channel is not None:
            self.footstep_channel.play(self.steps[index % len(self.steps)])

    def play_ui(self, sound: pygame.mixer.Sound) -> None:
        if self.available and self.ui_channel is not None:
            self.ui_channel.play(sound)

    def play_interaction(self, npc: str) -> None:
        """Play a loaded NPC interaction cue without interrupting UI sounds."""
        sound = self.interaction_sounds.get(f"{npc}_interact")
        if sound is not None:
            if self.available and self.interaction_channel is not None:
                self.interaction_channel.play(sound)

    def stop_footsteps(self) -> None:
        if self.footstep_channel is not None:
            self.footstep_channel.stop()
