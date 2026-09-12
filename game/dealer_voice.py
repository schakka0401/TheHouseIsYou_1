"""Responsive, non-overlapping playback for local Blackjack dealer clips."""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path

import pygame


DEBUG_DEALER_VOICE = True
DEALER_VOICE_MULTIPLIER = 0.90
DEALER_CHANNEL_INDEX = 2
MAX_DEALER_QUEUE = 3

PRERECORDED_LINES = (
    "dealer_intro",
    "dealer_round_1",
    "dealer_round_2",
    "dealer_round_3",
    "dealer_win_1",
    "dealer_win_2",
    "dealer_loss_1",
    "dealer_loss_2",
    "dealer_push_1",
    "dealer_thought_1",
    "dealer_thought_2",
    "dealer_thought_3",
    "dealer_final_round",
    "dealer_analysis",
    "dealer_simulation",
    "dealer_rematch",
)


class DealerVoicePriority(IntEnum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3


LOW = DealerVoicePriority.LOW
MEDIUM = DealerVoicePriority.MEDIUM
HIGH = DealerVoicePriority.HIGH


@dataclass(frozen=True)
class DealerLineRequest:
    name: str
    priority: DealerVoicePriority
    context: str | None = None


class DealerVoiceManager:
    """Preload local clips and serialize them through one dedicated channel."""

    def __init__(
        self,
        audio_manager,
        voice_directory: Path | None = None,
        *,
        channel=None,
        preloaded_sounds: dict[str, object] | None = None,
        voice_multiplier: float = DEALER_VOICE_MULTIPLIER,
    ) -> None:
        self.audio = audio_manager
        self.voice_multiplier = voice_multiplier
        self.voice_directory = voice_directory or (
            Path(__file__).resolve().parents[1]
            / "static"
            / "assets"
            / "audio"
            / "blackjack_voicelines"
        )
        self.channel = channel
        self.sounds: dict[str, object] = dict(preloaded_sounds or {})
        self.queue: list[DealerLineRequest] = []
        self.current: DealerLineRequest | None = None
        self.current_context: str | None = None

        if self.channel is None and getattr(self.audio, "available", False):
            try:
                if pygame.mixer.get_num_channels() <= DEALER_CHANNEL_INDEX:
                    pygame.mixer.set_num_channels(DEALER_CHANNEL_INDEX + 1)
                # Channels 0 and 1 belong to footsteps and UI. Reserve channel
                # 2 as well so Sound.play() cannot borrow the dealer channel.
                pygame.mixer.set_reserved(DEALER_CHANNEL_INDEX + 1)
                self.channel = pygame.mixer.Channel(DEALER_CHANNEL_INDEX)
            except pygame.error as error:
                self._debug(f"dealer channel unavailable: {error}")
                self.channel = None
        if preloaded_sounds is None and self.channel is not None:
            self._preload_prerecorded_lines()

    def _debug(self, message: str) -> None:
        if DEBUG_DEALER_VOICE:
            print(f"[DEALER VOICE] {message}")

    def _find_line_path(self, name: str) -> Path | None:
        matches = sorted(self.voice_directory.glob(f"{name}.*"))
        return matches[0] if matches else None

    def _preload_prerecorded_lines(self) -> None:
        for name in PRERECORDED_LINES:
            path = self._find_line_path(name)
            if path is None:
                self._debug(f"missing prerecorded line: {name}")
                continue
            try:
                self.sounds[name] = pygame.mixer.Sound(str(path))
            except (pygame.error, OSError) as error:
                self._debug(f"could not load {path.name}: {error}")
        self._debug(f"preloaded {len(self.sounds)} / {len(PRERECORDED_LINES)} local lines")

    def is_dealer_speaking(self) -> bool:
        return bool(self.channel and self.channel.get_busy())

    def _is_stale(self, request: DealerLineRequest) -> bool:
        return bool(request.context and request.context != self.current_context)

    def _effective_voice_volume(self) -> float:
        configured = getattr(self.audio, "sfx_volume", 0.0)
        return max(0.0, min(1.0, configured * self.voice_multiplier))

    def _start(self, request: DealerLineRequest) -> bool:
        sound = self.sounds.get(request.name)
        if sound is None or self.channel is None or self._is_stale(request):
            return False
        try:
            self.channel.set_volume(self._effective_voice_volume())
            self.channel.play(sound)
        except pygame.error as error:
            self._debug(f"dropped {request.name}: playback error {error}")
            return False
        self.current = request
        self._debug(f"start {request.name} priority={request.priority.name} queue={len(self.queue)}")
        return True

    def _play_next(self) -> bool:
        while self.queue:
            request = self.queue.pop(0)
            if self._is_stale(request):
                self._debug(f"dropped stale {request.name} queue={len(self.queue)}")
                continue
            if self._start(request):
                return True
        return False

    def play_dealer_line(
        self,
        name: str,
        priority: DealerVoicePriority,
        *,
        context: str | None = None,
    ) -> str:
        """Play now, briefly queue an important line, or drop stale chatter."""
        priority = DealerVoicePriority(priority)
        request = DealerLineRequest(name, priority, context)
        self._debug(f"requested {name} priority={priority.name} queue={len(self.queue)}")
        if self.channel is None or name not in self.sounds:
            self._debug(f"dropped {name}: unavailable")
            return "dropped"

        busy = self.is_dealer_speaking()
        if priority == LOW and (busy or self.queue):
            self._debug(f"dropped {name}: dealer already speaking")
            return "dropped"

        # A timely outcome matters more than generic round chatter. Stop only
        # the dedicated dealer channel, then begin the result immediately.
        if (
            priority == MEDIUM
            and busy
            and self.current is not None
            and self.current.priority == LOW
        ):
            self._debug(f"replaced generic {self.current.name} with {name}")
            self.channel.stop()
            self.current = None
            busy = False

        if not busy and not self.queue:
            if self._start(request):
                return "played"
            self._debug(f"dropped {name}: stale or playback failed")
            return "dropped"

        if priority == HIGH:
            removed = sum(queued.priority < HIGH for queued in self.queue)
            self.queue = [queued for queued in self.queue if queued.priority == HIGH]
            if removed:
                self._debug(f"cleared {removed} queued gameplay line(s)")

        if any(item.name == name and item.context == context for item in self.queue):
            self._debug(f"dropped duplicate {name}")
            return "dropped"
        if len(self.queue) >= MAX_DEALER_QUEUE:
            self._debug(f"dropped {name}: queue full")
            return "dropped"
        self.queue.append(request)
        self._debug(f"queued {name} priority={priority.name} queue={len(self.queue)}")
        return "queued"

    def clear_stale_dealer_lines(
        self,
        context: str,
        *,
        include_high: bool = False,
        stop_current: bool = False,
    ) -> None:
        """Advance context and discard queued dialogue that is no longer relevant."""
        self.current_context = context
        kept: list[DealerLineRequest] = []
        for request in self.queue:
            if self._is_stale(request) and (include_high or request.priority < HIGH):
                self._debug(f"cleared stale {request.name}")
            else:
                kept.append(request)
        self.queue = kept
        if stop_current and self.current is not None and self._is_stale(self.current):
            self._debug(f"stopped stale {self.current.name}")
            if self.channel is not None:
                self.channel.stop()
            self.current = None

    def update_dealer_voice(self) -> None:
        """Advance the queue without blocking the Pygame main loop."""
        if self.channel is None:
            return
        if self.current is not None and not self.channel.get_busy():
            self._debug(f"end {self.current.name} queue={len(self.queue)}")
            self.current = None
        if self.current is None and not self.channel.get_busy():
            self._play_next()
        if self.channel.get_busy():
            self.channel.set_volume(self._effective_voice_volume())

    def shutdown(self) -> None:
        """Stop only dealer speech when Blackjack closes."""
        self.queue.clear()
        if self.channel is not None:
            self.channel.stop()
        if self.current is not None:
            self._debug(f"end {self.current.name} (Blackjack closed)")
        self.current = None
