"""Polished Blackjack UI for the ten-round decision experiment."""
from __future__ import annotations


from pathlib import Path
import random
import threading

import pygame

from game.bankroll_simulator import simulate_long_term_bankroll
from game.blackjack_engine import BlackjackEngine, Scenario, SimulationStats, hand_value
from game.dealer_voice import DealerVoiceManager, HIGH, LOW, MEDIUM
from game.decision_tracker import DecisionRecord, DecisionTracker, confidence_probability
from game.menu import MenuButton, PRESS_MS as MENU_PRESS_MS, serif_font
from game.player_state import PlayerState


BLACKJACK_ROUNDS = 10
BLACKJACK_SESSION_ROUNDS = BLACKJACK_ROUNDS  # Compatibility for existing imports.
BANKROLL_SIMULATIONS = 10_000
BANKROLL_HORIZON = 100
ACTION_PRESS_MS = 110
DEBUG_RESULTS_LAYOUT = False

CONFIDENCE_TRACK = pygame.Rect(55, 535, 330, 14)
CONFIDENCE_CONFIRM = pygame.Rect(410, 515, 180, 54)
WAGER_FIELD = pygame.Rect(650, 558, 170, 42)
WAGER_CONFIRM = pygame.Rect(845, 552, 195, 48)
HIT_BUTTON = pygame.Rect(400, 610, 220, 55)
STAND_BUTTON = pygame.Rect(660, 610, 220, 55)

CHIP_VALUES = (1, 5, 10, 25, 50, 100)
CHIP_COLORS = ("white", "red", "blue", "green", "black", "purple")
CHIP_SOURCE_SIZE = (54, 54)
CHIP_DISPLAY_SIZE = (36, 36)
CHIP_TRAY_ORIGIN = (650, 480)
CHIP_TRAY_STEP = (46, 38)

DEALER_COMMENTS = (
    "Confidence can be expensive.",
    "The cards don't care how certain you were.",
    "Interesting. I'll remember that wager.",
    "A winning hand doesn't always make it a good decision.",
    "The house remembers.",
    "Fortune and judgment are not the same thing.",
    "Another decision for the ledger.",
)


class BlackjackGame:
    """Exactly one measured HIT/STAND choice in each of ten scenarios."""

    def __init__(
        self,
        screen: pygame.Surface,
        player_state: PlayerState,
        seed: int | None = None,
        simulations: int | None = None,
        menu_audio=None,
    ):
        self.screen = screen
        self.player_state = player_state
        self.menu_audio = menu_audio
        self.random = random.Random(seed)
        audio_manager = getattr(menu_audio, "manager", None)
        self.dealer_voice = DealerVoiceManager(audio_manager) if audio_manager is not None else None
        self.voice_session_number = 1
        self.generic_voice_count = 0
        self.results_voice_queued = False
        self.engine = BlackjackEngine(seed=seed, simulations=simulations)
        self.initial_bankroll = player_state.chips
        self.tracker = DecisionTracker()
        self.round_number = 0
        self.used_scenarios: set[tuple[str, ...]] = set()
        self.targets = ["EASY"] + ["MEDIUM"] * 6 + ["HARD"] * 3
        self.random.shuffle(self.targets)

        self.phase = "decision"
        self.scenario: Scenario | None = None
        self.scenario_stats: dict[str, SimulationStats] | None = None
        self.player_hand: list[tuple[str, str]] = []
        self.hand_bankroll_before = player_state.chips
        self.confidence_level: int | None = None
        self.confidence_confirmed = False
        self.wager_text = ""
        self.wager_confirmed = False
        self.current_bet = 0
        self.wager_focused = False
        self.hovered_action: str | None = None
        self.pressed_action: str | None = None
        self.action_pressed_at = 0
        self.pending_record: DecisionRecord | None = None
        self.result_started_at = 0
        self.result_title = ""
        self.result_change = ""
        self.dealer_comment = ""

        self.profile = None
        self.bankroll_projection = None
        self.analysis_thread: threading.Thread | None = None
        self.analysis_result = None
        self.analysis_error: Exception | None = None
        self.analysis_completed = 0
        self.analysis_total = BLACKJACK_ROUNDS

        results_path = Path(__file__).resolve().parents[1] / "static" / "assets" / "images" / "results_paper.png"
        self.results_paper_source = pygame.image.load(results_path).convert_alpha()
        self.results_paper_surface: pygame.Surface | None = None
        self.results_paper_rect = pygame.Rect(0, 0, 0, 0)
        self.results_safe_rect = pygame.Rect(0, 0, 0, 0)
        self.result_draw_items: list[tuple[pygame.Surface, pygame.Rect]] = []
        self.result_element_rects: list[pygame.Rect] = []
        self.rematch_button: MenuButton | None = None
        self.results_layout_screen_size: tuple[int, int] | None = None
        self.results_last_mouse_pos = pygame.mouse.get_pos()
        self.pending_rematch_at: int | None = None

        self.card_images: dict[tuple[str, str], pygame.Surface] = {}
        self.chip_images: dict[int, pygame.Surface] = {}
        self.chip_rects: list[tuple[pygame.Rect, int]] = []
        self.selected_chips: list[int] = []
        self.selected_chip_rects: list[tuple[pygame.Rect, int]] = []
        self.title_font = pygame.font.Font(None, 42)
        self.font = pygame.font.Font(None, 27)
        self.small_font = pygame.font.Font(None, 22)
        symbol_font = pygame.font.match_font("segoeuisymbol")
        self.action_font = pygame.font.Font(symbol_font, 25) if symbol_font else self.font
        self._load_card_images()
        self._load_chip_images()
        if self.dealer_voice is not None:
            entry_context = self._voice_context("entry")
            self.dealer_voice.clear_stale_dealer_lines(entry_context, include_high=True)
            self.dealer_voice.play_dealer_line("dealer_intro", HIGH, context=entry_context)
        self._queue_round()

    @property
    def asset_root(self) -> Path:
        return Path(__file__).resolve().parents[1] / "static" / "assets" / "cards"

    @property
    def actions_enabled(self) -> bool:
        return self.phase == "decision" and self.confidence_confirmed and self.wager_confirmed

    def _voice_context(self, stage: str) -> str:
        return f"blackjack:{self.voice_session_number}:{stage}"

    def _play_round_voice(self) -> None:
        if self.dealer_voice is None:
            return
        context = self._voice_context(f"round:{self.round_number}")
        self.dealer_voice.clear_stale_dealer_lines(context)
        if self.round_number == BLACKJACK_ROUNDS:
            self.dealer_voice.play_dealer_line("dealer_final_round", MEDIUM, context=context)
            return
        if self.round_number == 1 or self.generic_voice_count >= 3 or self.random.random() >= 0.38:
            return
        if self.random.random() < 0.75:
            name = self.random.choice(("dealer_round_1", "dealer_round_2", "dealer_round_3"))
        else:
            name = self.random.choice(("dealer_thought_1", "dealer_thought_2", "dealer_thought_3"))
        if self.dealer_voice.play_dealer_line(name, LOW, context=context) == "played":
            self.generic_voice_count += 1

    def _queue_results_voice(self) -> None:
        if self.dealer_voice is None or self.results_voice_queued:
            return
        self.results_voice_queued = True
        context = self._voice_context("results")
        self.dealer_voice.clear_stale_dealer_lines(context)
        self.dealer_voice.play_dealer_line("dealer_simulation", HIGH, context=context)
        self.dealer_voice.play_dealer_line("dealer_rematch", HIGH, context=context)

    def _load_card_images(self) -> None:
        for path in self.asset_root.glob("*.png"):
            if path.stem in {"card_back_1", "joker"}:
                continue
            parts = path.stem.split("_of_")
            if len(parts) != 2:
                continue
            rank = {"ace": "A", "jack": "J", "queen": "Q", "king": "K"}.get(parts[0], parts[0])
            image = pygame.image.load(path).convert_alpha()
            self.card_images[(rank, parts[1])] = pygame.transform.smoothscale(image, (105, 147))

    def _load_chip_images(self) -> None:
        """Preload the partner's chip artwork once for click-to-wager betting."""
        chip_root = Path(__file__).resolve().parents[1] / "static" / "assets" / "Card_Game_GFX" / "Chips"
        for value, color in zip(CHIP_VALUES, CHIP_COLORS):
            path = chip_root / f"chips_stacked_{color}.png"
            if not path.exists():
                print(f"Blackjack chip asset missing for {value}: {path}")
                continue
            image = pygame.image.load(path).convert_alpha()
            self.chip_images[value] = pygame.transform.smoothscale(image, CHIP_SOURCE_SIZE)

    def _chip_rects_for_screen(self) -> list[tuple[pygame.Rect, int]]:
        """Return the stable two-row chip tray hitboxes used by draw and input."""
        origin_x, origin_y = CHIP_TRAY_ORIGIN
        step_x, step_y = CHIP_TRAY_STEP
        return [
            (
                pygame.Rect(
                    origin_x + column * step_x,
                    origin_y + row * step_y,
                    *CHIP_DISPLAY_SIZE,
                ),
                value,
            )
            for row in range(2)
            for column, value in enumerate(CHIP_VALUES[row * 3:(row + 1) * 3])
        ]

    def start_new_session(self) -> None:
        """Future rematches use the same complete ten-round assessment."""
        self.voice_session_number += 1
        self.generic_voice_count = 0
        self.results_voice_queued = False
        if self.dealer_voice is not None:
            self.dealer_voice.clear_stale_dealer_lines(
                self._voice_context("entry"),
                include_high=True,
                stop_current=True,
            )
        self.initial_bankroll = self.player_state.chips
        self.tracker = DecisionTracker()
        self.round_number = 0
        self.used_scenarios.clear()
        self.targets = ["EASY"] + ["MEDIUM"] * 6 + ["HARD"] * 3
        self.random.shuffle(self.targets)
        self.profile = None
        self.bankroll_projection = None
        self.pending_rematch_at = None
        self._invalidate_results_layout()
        self._queue_round()

    def _invalidate_results_layout(self) -> None:
        self.results_layout_screen_size = None
        self.results_paper_surface = None
        self.rematch_button = None
        self.result_draw_items = []
        self.result_element_rects = []

    def _queue_round(self) -> None:
        if self.round_number >= BLACKJACK_ROUNDS or self.player_state.chips <= 0:
            self._finish_session()
            return
        target = self.targets[self.round_number]
        scenario, stats, _ = self.engine.generate_scenario(target, self.used_scenarios)
        self.scenario = scenario
        self.scenario_stats = stats
        self.used_scenarios.add(scenario.key)
        self.round_number += 1
        self.player_hand = list(scenario.player_cards)
        self.hand_bankroll_before = self.player_state.chips
        self.confidence_level = None
        self.confidence_confirmed = False
        self.wager_text = ""
        self.wager_confirmed = False
        self.current_bet = 0
        self.wager_focused = False
        self.selected_chips.clear()
        self.chip_rects = self._chip_rects_for_screen()
        self.hovered_action = None
        self.pressed_action = None
        self.pending_record = None
        self.phase = "decision"
        self._play_round_voice()

    def _valid_wager(self) -> bool:
        try:
            amount = int(self.wager_text)
        except (TypeError, ValueError):
            return False
        return 1 <= amount <= self.player_state.chips

    def _set_confidence(self, level: int) -> None:
        level = max(1, min(10, level))
        if level != self.confidence_level:
            self.confidence_level = level
            self.confidence_confirmed = False
            self.hovered_action = None

    def _set_confidence_from_mouse(self, x: int) -> None:
        fraction = max(0.0, min(1.0, (x - CONFIDENCE_TRACK.left) / CONFIDENCE_TRACK.width))
        self._set_confidence(round(1 + fraction * 9))

    def _confirm_confidence(self) -> None:
        if self.confidence_level is not None:
            self.confidence_confirmed = True

    def _set_wager_text(self, text: str) -> None:
        text = text[:6]
        if text != self.wager_text:
            self.wager_text = text
            self.wager_confirmed = False
            self.current_bet = 0
            self.hovered_action = None

    def _set_chip_wager(self, value: int) -> None:
        """Add one clicked chip and invalidate a previous wager confirmation."""
        if value not in CHIP_VALUES:
            return
        total = sum(self.selected_chips)
        if total + value > self.player_state.chips:
            return
        self.selected_chips.append(value)
        self.wager_text = str(total + value)
        self.wager_confirmed = False
        self.current_bet = 0
        self.wager_focused = True
        self.hovered_action = None

    def _remove_selected_chip(self, position: tuple[int, int]) -> bool:
        """Remove the clicked top chip from the wager stack."""
        for rect, _value in self.selected_chip_rects:
            if rect.collidepoint(position):
                self.selected_chips.pop()
                self.wager_text = str(sum(self.selected_chips)) if self.selected_chips else ""
                self.wager_confirmed = False
                self.current_bet = 0
                self.hovered_action = None
                return True
        return False

    def _confirm_wager(self) -> None:
        if self._valid_wager():
            self.current_bet = int(self.wager_text)
            self.wager_confirmed = True

    def _finish_session(self) -> None:
        if self.phase in {"analyzing", "results"}:
            return
        self.phase = "analyzing"
        if self.dealer_voice is not None:
            context = self._voice_context("results")
            self.dealer_voice.clear_stale_dealer_lines(context)
            self.dealer_voice.play_dealer_line("dealer_analysis", HIGH, context=context)
        self.analysis_completed = 0
        self.analysis_total = max(1, len(self.tracker.records))
        self.analysis_result = None
        self.analysis_error = None

        def analyze_session() -> None:
            try:
                profile = self.tracker.analyze(self.engine, self._analysis_progress)
                projection = simulate_long_term_bankroll(
                    self.tracker.records,
                    self.engine,
                    self.initial_bankroll,
                    simulations=BANKROLL_SIMULATIONS,
                    horizon=BANKROLL_HORIZON,
                )
                DecisionTracker.print_session_report(profile, projection)
                self.analysis_result = (profile, projection)
            except Exception as error:
                self.analysis_error = error

        self.analysis_thread = threading.Thread(target=analyze_session, daemon=True)
        self.analysis_thread.start()

    def _restart_session(self) -> None:
        self.__init__(self.screen, self.player_state)

    def _analysis_progress(self, completed: int, total: int) -> None:
        self.analysis_completed = completed
        self.analysis_total = max(1, total)

    def update(self) -> None:
        if self.dealer_voice is not None:
            self.dealer_voice.update_dealer_voice()
        if self.phase == "results" and self.pending_rematch_at is not None:
            if pygame.time.get_ticks() >= self.pending_rematch_at:
                self.pending_rematch_at = None
                self.start_new_session()
            return
        if (
            self.phase == "resolving"
            and self.pending_record is not None
            and pygame.time.get_ticks() - self.action_pressed_at >= ACTION_PRESS_MS
        ):
            self._resolve_pending_action()
        if self.phase == "analyzing" and self.analysis_thread is not None and not self.analysis_thread.is_alive():
            if self.analysis_error:
                                raise self.analysis_error
            self.profile, self.bankroll_projection = self.analysis_result
            self._invalidate_results_layout()
            self.phase = "results"
            self._queue_results_voice()

    def _make_record(self, action: str) -> DecisionRecord:
        assert self.scenario is not None
        assert self.scenario_stats is not None
        assert self.confidence_level is not None
        record = DecisionRecord(
            round_number=self.round_number,
            player_cards=[f"{rank} of {suit}" for rank, suit in self.scenario.player_cards],
            player_total=hand_value(self.scenario.player_cards)[0],
            dealer_upcard=f"{self.scenario.dealer_upcard[0]} of {self.scenario.dealer_upcard[1]}",
            player_action=action,
            confidence_level=self.confidence_level,
            confidence_probability=confidence_probability(self.confidence_level),
            bet=self.current_bet,
            bankroll_before=self.hand_bankroll_before,
            bankroll_after=self.hand_bankroll_before,
            actual_round_result="pending",
            scenario=self.scenario,
        )
        DecisionTracker.apply_evaluation(record, self.scenario_stats, self.engine.difficulty)
        return record

    def _take_action(self, action: str) -> None:
        if not self.actions_enabled or action not in {"hit", "stand"}:
            return
        # Lock immediately. No event can produce a second decision this round.
        self.phase = "resolving"
        self.pressed_action = action
        self.action_pressed_at = pygame.time.get_ticks()
        self.pending_record = self._make_record(action)
        self.tracker.add(self.pending_record)

    def _resolve_pending_action(self) -> None:
        record = self.pending_record
        assert record is not None
        assert self.scenario_stats is not None
        result = self.engine.sample_outcome(self.scenario_stats[record.player_action])
        change = self.current_bet if result == "win" else -self.current_bet if result == "loss" else 0
        self.player_state.chips += change
        record.actual_round_result = result
        record.bankroll_change = change
        record.bankroll_after = self.player_state.chips
        record.dealer_comment = self.random.choice(DEALER_COMMENTS)

        if result == "win":
            self.result_title = "THE HOUSE PAYS."
            self.result_change = f"+{self.current_bet} CHIPS"
        elif result == "loss":
            self.result_title = "THE HOUSE TAKES IT."
            self.result_change = f"-{self.current_bet} CHIPS"
        else:
            self.result_title = "PUSH."
            self.result_change = "NO CHANGE."
        self.dealer_comment = record.dealer_comment
        self.result_started_at = pygame.time.get_ticks()
        self.phase = "result"
        if self.dealer_voice is not None:
            context = self._voice_context(f"round:{self.round_number}")
            result_line = {
                "win": self.random.choice(("dealer_win_1", "dealer_win_2")),
                "loss": self.random.choice(("dealer_loss_1", "dealer_loss_2")),
                "push": "dealer_push_1",
            }[result]
            self.dealer_voice.play_dealer_line(result_line, MEDIUM, context=context)
        print(f"\n{self.result_title}\n{self.result_change}")
        print(f'"{self.dealer_comment}"')
        DecisionTracker.print_round_debug(record)

    def handle_event(self, event: pygame.event.Event) -> str | None:
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            if self.dealer_voice is not None:
                self.dealer_voice.shutdown()
            return "room"
        if self.phase in {"analyzing", "resolving"}:
            return None
        if self.phase == "results":
            self._ensure_results_layout()
            now = pygame.time.get_ticks()
            if event.type == pygame.VIDEORESIZE:
                self._invalidate_results_layout()
            elif event.type == pygame.MOUSEMOTION and event.pos != self.results_last_mouse_pos:
                self.results_last_mouse_pos = event.pos
                hovered = bool(self.rematch_button and self.rematch_button.contains(event.pos))
                was_selected = bool(self.rematch_button and self.rematch_button.selected)
                if self.rematch_button:
                    self.rematch_button.selected = hovered
                if hovered and not was_selected and self.menu_audio:
                    self.menu_audio.switch()
            elif (
                event.type == pygame.MOUSEBUTTONDOWN
                and event.button == 1
                and self.rematch_button
                and self.rematch_button.contains(event.pos)
                and self.pending_rematch_at is None
            ):
                self.rematch_button.selected = True
                self.rematch_button.press(now)
                if self.menu_audio:
                    self.menu_audio.click()
                self.pending_rematch_at = now + MENU_PRESS_MS
            if (
                event.type == pygame.KEYDOWN
                and event.key in (pygame.K_RETURN, pygame.K_SPACE)
                and self.pending_rematch_at is None
            ):
                if self.rematch_button:
                    self.rematch_button.selected = True
                    self.rematch_button.press(now)
                if self.menu_audio:
                    self.menu_audio.click()
                self.pending_rematch_at = now + MENU_PRESS_MS
            return None
        if self.phase == "result":
            if event.type == pygame.KEYDOWN and event.key in (pygame.K_RETURN, pygame.K_SPACE):
                self._queue_round()
            return None
        if self.phase != "decision":
            return None

        if event.type == pygame.MOUSEMOTION:
            if event.buttons[0] and CONFIDENCE_TRACK.inflate(20, 30).collidepoint(event.pos):
                self._set_confidence_from_mouse(event.pos[0])
            if self.actions_enabled:
                if HIT_BUTTON.collidepoint(event.pos):
                    self.hovered_action = "hit"
                elif STAND_BUTTON.collidepoint(event.pos):
                    self.hovered_action = "stand"
                else:
                    self.hovered_action = None
            else:
                self.hovered_action = None
            return None

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if CONFIDENCE_TRACK.inflate(20, 30).collidepoint(event.pos):
                self.wager_focused = False
                self._set_confidence_from_mouse(event.pos[0])
            elif CONFIDENCE_CONFIRM.collidepoint(event.pos):
                self.wager_focused = False
                self._confirm_confidence()
            elif any(rect.collidepoint(event.pos) for rect, _value in self.chip_rects):
                for rect, value in self.chip_rects:
                    if rect.collidepoint(event.pos):
                        self._set_chip_wager(value)
                        break
            elif self._remove_selected_chip(event.pos):
                self.wager_focused = True
            elif WAGER_FIELD.collidepoint(event.pos):
                # Wagers are made with chips. The field is a read-only summary.
                self.wager_focused = True
            elif WAGER_CONFIRM.collidepoint(event.pos):
                self.wager_focused = True
                self._confirm_wager()
            elif self.actions_enabled and HIT_BUTTON.collidepoint(event.pos):
                self._take_action("hit")
            elif self.actions_enabled and STAND_BUTTON.collidepoint(event.pos):
                self._take_action("stand")
            return None

        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_LEFT, pygame.K_DOWN):
                self._set_confidence((self.confidence_level or 2) - 1)
            elif event.key in (pygame.K_RIGHT, pygame.K_UP):
                self._set_confidence((self.confidence_level or 0) + 1)
            elif event.key == pygame.K_c:
                self._confirm_confidence()
            elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
                if not self.confidence_confirmed:
                    self._confirm_confidence()
                elif not self.wager_confirmed:
                    self._confirm_wager()
            elif event.key == pygame.K_BACKSPACE:
                if self.selected_chips:
                    self.selected_chips.pop()
                    self.wager_text = str(sum(self.selected_chips)) if self.selected_chips else ""
                    self.wager_confirmed = False
                    self.current_bet = 0
            elif pygame.K_0 <= event.key <= pygame.K_9:
                digit = event.key - pygame.K_0
                if not self.confidence_confirmed:
                    self._set_confidence(10 if digit == 0 else digit)
            elif self.actions_enabled and event.key == pygame.K_h:
                self._take_action("hit")
            elif self.actions_enabled and event.key == pygame.K_s:
                self._take_action("stand")
        return None

    def _text(self, text, position, size=27, color=(245, 233, 190)) -> None:
        self.screen.blit(pygame.font.Font(None, size).render(text, True, color), position)

    def _draw_card(self, card, position, hidden=False) -> None:
        if hidden:
            pygame.draw.rect(self.screen, "#8b2020", (*position, 105, 147), border_radius=8)
            pygame.draw.rect(self.screen, "#f7e9b9", (*position, 105, 147), width=2, border_radius=8)
        elif card in self.card_images:
            self.screen.blit(self.card_images[card], position)

    def _draw_hands(self) -> None:
        assert self.scenario is not None
        self._draw_card(self.scenario.dealer_upcard, (520, 65))
        self._draw_card(None, (640, 65), hidden=True)
        spacing = 120 if len(self.player_hand) <= 5 else 105
        total_width = 105 + spacing * (len(self.player_hand) - 1)
        player_x = max(35, (self.screen.get_width() - total_width) // 2)
        for index, card in enumerate(self.player_hand):
            self._draw_card(card, (player_x + index * spacing, 280))

    def _draw_small_button(self, rect: pygame.Rect, label: str, confirmed: bool, enabled: bool = True) -> None:
        fill = "#386641" if confirmed else "#5f421f" if enabled else "#383838"
        border = "#f1d277" if enabled else "#777777"
        pygame.draw.rect(self.screen, fill, rect, border_radius=8)
        pygame.draw.rect(self.screen, border, rect, width=2, border_radius=8)
        text = self.small_font.render("CONFIRMED" if confirmed else label, True, "#f7e9b9" if enabled else "#999999")
        self.screen.blit(text, text.get_rect(center=rect.center))

    def _draw_action_button(self, rect: pygame.Rect, action: str, label: str, color: str) -> None:
        enabled = self.actions_enabled or (
            self.phase == "resolving" and self.confidence_confirmed and self.wager_confirmed
        )
        pressed = self.phase == "resolving" and self.pressed_action == action
        if pressed:
            draw_rect = rect.inflate(-5, -4).move(0, 3)
        elif enabled and self.hovered_action == action:
            draw_rect = rect.inflate(8, 6)
        else:
            draw_rect = rect
        fill = color if enabled else "#454545"
        border = "#f7e9b9" if enabled else "#777777"
        pygame.draw.rect(self.screen, fill, draw_rect, border_radius=8)
        pygame.draw.rect(self.screen, border, draw_rect, width=2, border_radius=8)
        text_color = "#f7e9b9" if enabled else "#929292"
        text = self.action_font.render(label, True, text_color)
        self.screen.blit(text, text.get_rect(center=draw_rect.center))

    def _draw_controls(self) -> None:
        self._text("CONFIDENCE: Better decision, not chance to win", (55, 490), 22, "#d8d0b8")
        pygame.draw.rect(self.screen, "#3b2418", CONFIDENCE_TRACK, border_radius=7)
        pygame.draw.rect(self.screen, "#b88732", CONFIDENCE_TRACK, width=2, border_radius=7)
        if self.confidence_level is not None:
            marker = CONFIDENCE_TRACK.left + round((self.confidence_level - 1) * CONFIDENCE_TRACK.width / 9)
            pygame.draw.circle(self.screen, "#f1d277", (marker, CONFIDENCE_TRACK.centery), 11)
            confidence_text = f"{self.confidence_level}/10  {confidence_probability(self.confidence_level):.0%}"
        else:
            confidence_text = "Choose 1-10"
        self._text(confidence_text, (150, 558), 22, "#f1d277")
        self._draw_small_button(CONFIDENCE_CONFIRM, "CONFIRM", self.confidence_confirmed, self.confidence_level is not None)

        self._text(f"WAGER (1-{self.player_state.chips})", (650, 438), 22, "#d8d0b8")
        self._text("CLICK CHIPS TO BUILD YOUR WAGER", (650, 462), 16, "#b9ad8f")
        self._draw_wager_chips()
        field_color = "#f1d277" if self.wager_focused else "#b88732"
        pygame.draw.rect(self.screen, "#24170f", WAGER_FIELD, border_radius=8)
        pygame.draw.rect(self.screen, field_color, WAGER_FIELD, width=2, border_radius=8)
        wager = self.font.render(f"{self.wager_text or '_'} CHIPS", True, "#f1d277")
        wager_center = (WAGER_FIELD.centerx + (14 if self.selected_chips else 0), WAGER_FIELD.centery)
        self._draw_selected_chips()
        self.screen.blit(wager, wager.get_rect(center=wager_center))
        self._draw_small_button(WAGER_CONFIRM, "CONFIRM", self.wager_confirmed, self._valid_wager())

        self._draw_action_button(HIT_BUTTON, "hit", "♠  HIT  ♥", "#286db2")
        self._draw_action_button(STAND_BUTTON, "stand", "♦  STAND  ♣", "#b52f38")

    def _draw_wager_chips(self) -> None:
        self.chip_rects = self._chip_rects_for_screen()
        for rect, value in self.chip_rects:
            image = self.chip_images.get(value)
            if image is None:
                continue
            chip = pygame.transform.smoothscale(image, CHIP_DISPLAY_SIZE)
            if value > self.player_state.chips:
                chip = chip.copy()
                chip.set_alpha(80)
            self.screen.blit(chip, rect)
            value_surface = pygame.font.Font(None, 16).render(str(value), True, "#24170f")
            self.screen.blit(value_surface, value_surface.get_rect(center=rect.center))

    def _draw_selected_chips(self) -> None:
        """Show a compact removable stack inside the wager summary field."""
        self.selected_chip_rects = []
        if not self.selected_chips:
            return
        visible_layers = min(len(self.selected_chips), 8)
        base = pygame.Rect(WAGER_FIELD.left + 6, WAGER_FIELD.top + 3, 30, 30)
        click_rect = base.move(0, -(visible_layers - 1) * 2)
        click_rect.height += (visible_layers - 1) * 2
        self.selected_chip_rects.append((click_rect, self.selected_chips[-1]))
        for index, value in enumerate(self.selected_chips[-visible_layers:]):
            image = self.chip_images.get(value)
            if image is None:
                continue
            chip = pygame.transform.smoothscale(image, base.size)
            self.screen.blit(chip, base.move(0, -index * 2))

    def draw(self) -> None:
        self.screen.fill("#154734")
        if self.phase == "analyzing":
            self.screen.blit(self.title_font.render("ANALYZING YOUR DECISIONS...", True, "#f7e9b9"), (35, 25))
            completed, total = self.analysis_completed, max(1, self.analysis_total)
            self._text("Running long-term session simulation...", (350, 330), 31, "#f1d277")
            self._text(f"Preparing report {completed} / {total}", (430, 385), 27)
            pygame.draw.rect(self.screen, "#3b2418", (310, 440, 660, 26), border_radius=10)
            pygame.draw.rect(self.screen, "#d29a32", (310, 440, int(660 * completed / total), 26), border_radius=10)
            return
        if self.phase == "results":
            self._draw_results()
            return

        self.screen.blit(self.title_font.render("BLACKJACK DECISION TABLE", True, "#f7e9b9"), (35, 25))
        self._text(f"Round {self.round_number}/{BLACKJACK_ROUNDS}", (1010, 35))
        self._text(f"Shared bankroll: {self.player_state.chips} chips", (35, 80))
        self._draw_hands()
        player_total, _ = hand_value(self.player_hand)
        self._text(f"DEALER SHOWS: {self.scenario.dealer_upcard[0]}", (50, 235), 29)
        self._text(f"YOUR HAND: {player_total}", (50, 455), 29)

        if self.phase in {"decision", "resolving"}:
            self._draw_controls()
        elif self.phase == "result":
            panel = pygame.Rect(255, 485, 770, 180)
            pygame.draw.rect(self.screen, "#21130f", panel, border_radius=14)
            pygame.draw.rect(self.screen, "#d29a32", panel, width=3, border_radius=14)
            title = self.title_font.render(self.result_title, True, "#f1d277")
            self.screen.blit(title, title.get_rect(center=(panel.centerx, 525)))
            change = self.font.render(self.result_change, True, "#f7e9b9")
            self.screen.blit(change, change.get_rect(center=(panel.centerx, 565)))
            comment = self.small_font.render(f'"{self.dealer_comment}"', True, "#d8d0b8")
            self.screen.blit(comment, comment.get_rect(center=(panel.centerx, 605)))
            prompt = self.small_font.render("ENTER: next independent scenario", True, "#d8d0b8")
            self.screen.blit(prompt, prompt.get_rect(center=(panel.centerx, 640)))
        self._text("ESC: return to casino floor", (35, 680), 22, "#d8d0b8")

    def _draw_results(self) -> None:
        self._ensure_results_layout()
        self.screen.fill((7, 3, 4))
        self.screen.blit(self.results_paper_surface, self.results_paper_rect)
        for surface, rect in self.result_draw_items:
            self.screen.blit(surface, rect)
        if self.rematch_button:
            self.rematch_button.draw(self.screen, pygame.time.get_ticks())
        if DEBUG_RESULTS_LAYOUT:
            pygame.draw.rect(self.screen, (70, 220, 255), self.results_paper_rect, 2)
            pygame.draw.rect(self.screen, (70, 255, 120), self.results_safe_rect, 2)
            for rect in self.result_element_rects:
                pygame.draw.rect(self.screen, (255, 70, 90), rect, 1)

    @staticmethod
    def _wrap_result_text(text: str, font: pygame.font.Font, max_width: int) -> list[str]:
        lines: list[str] = []
        current: list[str] = []
        for word in text.split():
            candidate = " ".join((*current, word))
            if current and font.size(candidate)[0] > max_width:
                lines.append(" ".join(current))
                current = [word]
            else:
                current.append(word)
        if current:
            lines.append(" ".join(current))
        return lines

    @staticmethod
    def _short_result_findings(findings: list[str], font: pygame.font.Font, max_width: int) -> list[str]:
        shorter = {
            "You tended to be more confident than your accuracy justified.":
                "Your confidence exceeded your accuracy.",
            "This session suggests you underestimated your decision accuracy.":
                "You underestimated your decision accuracy.",
            "Your largest wagers tended to occur on your weaker decisions.":
                "Your largest wagers landed on weaker decisions.",
            "Your wager sizing exposed a large portion of your bankroll to one decision.":
                "One wager exposed a large share of your bankroll.",
            "Several mistakes were close decisions and cost little expected value.":
                "Your mistakes were close and cost little expected value.",
            "An all-in wager drove most projected risk, despite strong card decisions.":
                "An all-in wager drove most projected risk.",
            "You put nearly your entire bankroll at risk on a single decision.":
                "One wager put nearly your entire bankroll at risk.",
            "Your final bankroll finished well above expectation; luck was on your side.":
                "Luck put your final bankroll well above expectation.",
            "Your bankroll finished below expectation; your decisions were better than the chip count suggests.":
                "Your decisions were better than the final chip count suggests.",
            "Your final bankroll was reasonably close to the expected value of your choices.":
                "Your final bankroll was close to expectation.",
        }
        selected = [shorter.get(finding, finding) for finding in findings]
        wrapped = BlackjackGame._wrap_result_text(" ".join(selected), font, max_width)
        return wrapped[:5]

    def _build_results_content(
        self,
        safe_rect: pygame.Rect,
        paper_rect: pygame.Rect,
        body_reduction: int,
        label_reduction: int,
        gap_scale: float,
        finding_count: int,
    ) -> tuple[list[tuple[pygame.Surface, pygame.Rect]], list[pygame.Rect], MenuButton] | None:
        ph = paper_rect.height
        profile = self.profile or self.tracker.profile()
        projection = self.bankroll_projection or {}
        player_projection = projection.get("player", {})
        optimal_projection = projection.get("optimal", {})
        capped_projection = projection.get("risk_capped", {})
        dark_brown = (53, 31, 24)
        burgundy = (91, 20, 30)
        score_red = (126, 22, 34)
        muted_brown = (84, 55, 39)

        compact = body_reduction >= 3
        title_font = serif_font(max(17, round(ph * 0.040)), True)
        score_label_font = serif_font(max(13, round(ph * 0.030) - label_reduction), True)
        score_value_font = serif_font(max(26, round(ph * 0.060)), True)
        section_font = serif_font(max(11, round(ph * 0.025) - label_reduction), True)
        body_font = serif_font(max(10, round(ph * 0.021) - body_reduction))
        small_font = serif_font(max(9, round(ph * 0.018) - body_reduction))
        optimal_value_font = serif_font(max(15, round(ph * 0.034) - body_reduction), True)

        line_gap = max(1, round(ph * 0.002 * gap_scale))
        small_gap = max(2, round(ph * 0.006 * gap_scale))
        section_gap = max(4, round(ph * 0.011 * gap_scale))
        cursor_y = safe_rect.top
        items: list[tuple[pygame.Surface, pygame.Rect]] = []
        rects: list[pygame.Rect] = []

        def add_lines(lines: list[str], font: pygame.font.Font, color, gap_after: int = 0) -> None:
            nonlocal cursor_y
            for line in lines:
                surface = font.render(line, True, color)
                rect = surface.get_rect(midtop=(safe_rect.centerx, cursor_y))
                items.append((surface, rect))
                rects.append(rect)
                cursor_y = rect.bottom + line_gap
            cursor_y += max(0, gap_after - line_gap)

        add_lines(["THE HOUSE SAYS"], title_font, burgundy, section_gap)
        add_lines(["DECISION SCORE"], score_label_font, muted_brown, small_gap)
        add_lines([f"{profile.get('decision_score', 0)} / 100"], score_value_font, score_red, section_gap)
        add_lines(["OPTIMAL DECISIONS"], section_font, burgundy, small_gap)
        add_lines(
            [f"{profile.get('correct_decisions', 0)} / {profile.get('total_decisions', 0)}"],
            optimal_value_font,
            dark_brown,
            section_gap,
        )

        confidence = profile.get("average_confidence", 0.0)
        accuracy = profile.get("accuracy", 0.0)
        gap = profile.get("calibration_gap", 0.0)
        if abs(gap) < 0.05:
            calibration_line = "Confidence was well calibrated"
        elif gap > 0:
            calibration_line = f"Overconfident by {abs(gap) * 100:.0f} points"
        else:
            calibration_line = f"Underconfident by {abs(gap) * 100:.0f} points"
        add_lines(["CONFIDENCE"], section_font, burgundy, small_gap)
        add_lines(
            [f"{confidence:.0%} confidence vs {accuracy:.0%} accuracy", calibration_line],
            body_font,
            dark_brown,
            section_gap,
        )

        add_lines(["BANKROLL"], section_font, burgundy, small_gap)
        if compact:
            bankroll_lines = [
                f"Actual: {profile.get('actual_bankroll', 0)} chips",
                f"Expected, your choices: {profile.get('expected_player_bankroll', 0):.0f}",
                f"Optimal HIT/STAND, same wagers: {profile.get('expected_optimal_bankroll', 0):.0f}",
            ]
        else:
            bankroll_lines = [
                f"Actual result: {profile.get('actual_bankroll', 0)} chips",
                f"Expected from your choices: {profile.get('expected_player_bankroll', 0):.0f} chips",
                f"Expected with optimal HIT/STAND: {profile.get('expected_optimal_bankroll', 0):.0f} chips",
            ]
        wrapped_bankroll: list[str] = []
        for line in bankroll_lines:
            wrapped_bankroll.extend(self._wrap_result_text(line, body_font, safe_rect.width))
        add_lines(wrapped_bankroll, body_font, dark_brown, small_gap)
        if compact:
            cursor_y += max(0, section_gap - small_gap)
        else:
            add_lines(["Expected values use the same wagers."], small_font, muted_brown, section_gap)

        add_lines(["WHAT THE HOUSE NOTICED"], section_font, burgundy, small_gap)
        comment_width = round(safe_rect.width * 0.84)
        all_findings = list(profile.get("findings", []))
        # Decision quality is already stated by the score and optimal count;
        # reserve this short paragraph for the separate risk and luck stories.
        findings = all_findings[1:3] if len(all_findings) >= 3 else all_findings[:finding_count]
        comment_lines = self._short_result_findings(findings, small_font, comment_width)
        add_lines(comment_lines, small_font, dark_brown, section_gap)

        horizon = projection.get("horizon", BANKROLL_HORIZON)
        add_lines([f"{horizon}-DECISION SIMULATION"], section_font, burgundy, small_gap)
        add_lines(["Repeating your observed betting behavior"], small_font, muted_brown, small_gap)
        risk_cap = projection.get("risk_cap", 0.10)
        simulation_lines = [
            f"Your play: {player_projection.get('bankruptcy_probability', 0):.0%} bankruptcy",
            f"Optimal / same bets: {optimal_projection.get('bankruptcy_probability', 0):.0%} bankruptcy",
            f"Optimal / {risk_cap:.0%} risk cap: {capped_projection.get('bankruptcy_probability', 0):.0%} bankruptcy",
        ]
        wrapped_simulation: list[str] = []
        for line in simulation_lines:
            wrapped_simulation.extend(self._wrap_result_text(line, body_font, safe_rect.width))
        add_lines(wrapped_simulation, body_font, dark_brown, section_gap)

        button_width = round(safe_rect.width * 0.74)
        button_height = max(32, round(ph * 0.052))
        button_bottom = min(
            safe_rect.bottom - max(1, round(ph * 0.005)),
            paper_rect.top + round(ph * 0.875),
        )
        button_rect = pygame.Rect(0, 0, button_width, button_height)
        button_rect.midbottom = (safe_rect.centerx, button_bottom)
        if cursor_y >= button_rect.top:
            if DEBUG_RESULTS_LAYOUT:
                print(
                    "RESULTS LAYOUT OVERFLOW:",
                    f"content_bottom={cursor_y}",
                    f"button_top={button_rect.top}",
                    f"body_reduction={body_reduction}",
                    f"label_reduction={label_reduction}",
                    f"gap_scale={gap_scale}",
                    f"finding_count={finding_count}",
                )
            return None
        button_size = max(11, round(ph * 0.020) - body_reduction)
        button_face = serif_font(button_size, True)
        while button_size > 10 and button_face.size("CARE TO PROVE ME WRONG?")[0] > button_width * 0.82:
            button_size -= 1
            button_face = serif_font(button_size, True)
        button = MenuButton("CARE TO PROVE ME WRONG?", 0, button_face, button_rect)
        rects.append(button_rect)
        return items, rects, button

    def _ensure_results_layout(self) -> None:
        screen_size = self.screen.get_size()
        if self.results_layout_screen_size == screen_size and self.results_paper_surface is not None:
            return

        source_width, source_height = self.results_paper_source.get_size()
        scale = min(
            (screen_size[0] * 0.86) / source_width,
            (screen_size[1] * 0.94) / source_height,
        )
        paper_size = (max(1, round(source_width * scale)), max(1, round(source_height * scale)))
        paper_surface = pygame.transform.smoothscale(self.results_paper_source, paper_size)
        paper_rect = paper_surface.get_rect(center=self.screen.get_rect().center)
        safe_left = paper_rect.left + round(paper_rect.width * 0.13)
        safe_right = paper_rect.left + round(paper_rect.width * 0.87)
        safe_top = paper_rect.top + round(paper_rect.height * 0.12)
        safe_bottom = paper_rect.top + round(paper_rect.height * 0.88)
        safe_rect = pygame.Rect(safe_left, safe_top, safe_right - safe_left, safe_bottom - safe_top)

        layout = None
        for body_reduction, label_reduction, gap_scale, finding_count in (
            (0, 0, 0.82, 3),
            (1, 0, 0.68, 3),
            (2, 1, 0.50, 2),
            (3, 2, 0.36, 2),
        ):
            layout = self._build_results_content(
                safe_rect,
                paper_rect,
                body_reduction,
                label_reduction,
                gap_scale,
                finding_count,
            )
            if layout is not None:
                break
        if layout is None:
            raise AssertionError("Blackjack results content does not fit the paper's printable area")

        items, rects, button = layout
        for rect in rects:
            assert rect.left >= safe_rect.left
            assert rect.right <= safe_rect.right
            assert rect.top >= safe_rect.top
            assert rect.bottom <= safe_rect.bottom
        for previous, current in zip(rects, rects[1:]):
            assert previous.bottom < current.top

        self.results_paper_surface = paper_surface
        self.results_paper_rect = paper_rect
        self.results_safe_rect = safe_rect
        self.result_draw_items = items
        self.result_element_rects = rects
        self.rematch_button = button
        self.results_layout_screen_size = screen_size
