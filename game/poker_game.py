"""Functional first-pass UI for the five-snapshot Poker experiment."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import random
import threading

import pygame

from game.menu import MenuButton, PRESS_MS as MENU_PRESS_MS, serif_font
from game.dealer_voice import HIGH, LOW
from game.player_state import PlayerState
from game.poker_models import Card, PokerDecisionRecord, PokerScenario, PreparedPokerRound, card_code
from game.poker_scenarios import EQUITY_SIMULATIONS, POKER_ROUNDS, PokerScenarioGenerator
from game.poker_dealer import PokerDealerOverlay
from game.poker_tracker import PokerSessionTracker


CONFIDENCE_TRACK = pygame.Rect(80, 560, 400, 14)
CARD_SIZE = (82, 115)
CHIP_VALUES = (1, 5, 10, 25, 50, 100)
CHIP_COLORS = ("white", "red", "blue", "green", "black", "purple")
CHIP_SOURCE_SIZE = (54, 54)
CHIP_DISPLAY_SIZE = (36, 36)
CHIP_TRAY_ORIGIN = (565, 575)
CHIP_TRAY_STEP = (70, 52)
WAGER_FIELD = pygame.Rect(800, 585, 170, 42)
DEBUG_POKER_RESULTS_LAYOUT = False
# Temporary console aid for testing a perfect Poker session. Keep off for normal play.
DEBUG_PRINT_POKER_BEST_MOVES = True


@dataclass(frozen=True)
class PokerTableRow:
    """One honest player-facing seat row derived from the scenario history."""

    position: str
    name: str
    stack: int
    last_action: str
    state: str
    amount_still_to_call: int
    is_you: bool = False

    @property
    def status_text(self) -> str:
        if self.is_you:
            return self.last_action
        pieces = [self.last_action]
        if self.state != self.last_action:
            pieces.append(self.state)
        if self.amount_still_to_call:
            pieces.append(f"${self.amount_still_to_call} MORE TO CALL")
        return " | ".join(piece for piece in pieces if piece)


def build_table_rows(
    scenario: PokerScenario,
    record: PokerDecisionRecord | None = None,
) -> tuple[PokerTableRow, ...]:
    """Place YOU among the real seats and expose each seat's current state."""

    opponent_by_position = {opponent.position: opponent for opponent in scenario.opponents}
    occupied = set(opponent_by_position) | {scenario.hero_position}
    action_order = (
        ("UTG", "MP", "CO", "BTN", "SB", "BB")
        if scenario.street == "preflop"
        else ("SB", "BB", "UTG", "MP", "CO", "BTN")
    )
    ordered_positions = [position for position in action_order if position in occupied]
    ordered_positions.extend(sorted(occupied.difference(ordered_positions)))

    rows: list[PokerTableRow] = []
    for position in ordered_positions:
        if position == scenario.hero_position:
            final_action = record.final_action_history[-1] if record is not None else None
            if final_action is None:
                last_action = "ACTION ON YOU"
                state = "ACTIVE"
            else:
                last_action = final_action.describe().removeprefix("YOU ")
                state = "FOLDED" if final_action.action == "fold" else "ACTIVE"
            rows.append(PokerTableRow(
                position=position,
                name="YOU",
                stack=scenario.hero_stack,
                last_action=last_action,
                state=state,
                amount_still_to_call=0,
                is_you=True,
            ))
            continue

        opponent = opponent_by_position[position]
        amount_still_to_call = (
            max(0, scenario.current_bet - opponent.contribution)
            if not opponent.folded else 0
        )
        rows.append(PokerTableRow(
            position=position,
            name=position,
            stack=opponent.stack,
            last_action=opponent.status,
            state="FOLDED" if opponent.folded else "ACTIVE",
            amount_still_to_call=amount_still_to_call,
        ))
    return tuple(rows)


class PokerGame:
    """Exactly one measured decision for each of five independent scenarios."""

    def __init__(
        self,
        screen: pygame.Surface,
        player_state: PlayerState,
        seed: int | None = None,
        equity_simulations: int = EQUITY_SIMULATIONS,
        menu_audio=None,
    ) -> None:
        self.screen = screen
        self.player_state = player_state
        self.menu_audio = menu_audio
        self.voice_session_number = 1
        self.voice_random = random.Random(seed)
        audio_manager = getattr(menu_audio, "manager", None)
        self.poker_dealer = PokerDealerOverlay(screen, audio_manager, seed=seed)
        self.generator = PokerScenarioGenerator(seed=seed, equity_simulations=equity_simulations)
        self.tracker = PokerSessionTracker()
        self.round_number = 0
        self.phase = "loading"
        self.prepared: PreparedPokerRound | None = None
        self.record: PokerDecisionRecord | None = None
        self.summary: dict | None = None
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
        self.confidence_percent: int | None = None
        self.selected_action: str | None = None
        self.selected_amount: int | None = None
        self.loading_thread: threading.Thread | None = None
        self.loading_result: PreparedPokerRound | None = None
        self.loading_error: Exception | None = None
        self.action_buttons: list[tuple[pygame.Rect, str]] = []
        self.size_buttons: list[tuple[pygame.Rect, int]] = []
        self.lock_button_rect = pygame.Rect(990, 610, 230, 52)
        self.hover_token: tuple[str, int | str] | None = None
        self.card_images: dict[Card, pygame.Surface] = {}
        self.chip_images: dict[int, pygame.Surface] = {}
        self.chip_rects: list[tuple[pygame.Rect, int]] = []
        self.selected_chip_rects: list[tuple[pygame.Rect, int]] = []
        self.selected_chips: list[int] = []
        self.title_font = serif_font(44, True)
        self.font = serif_font(26)
        self.small_font = serif_font(20)
        self.button_face = serif_font(24, True)
        self._load_card_images()
        self._load_chip_images()
        self.on_poker_session_start()
        self._start_round_loading()

    @property
    def asset_root(self) -> Path:
        return Path(__file__).resolve().parents[1] / "static" / "assets" / "cards"

    def _load_card_images(self) -> None:
        for path in self.asset_root.glob("*.png"):
            if path.stem in {"card_back_1", "joker"}:
                continue
            parts = path.stem.split("_of_")
            if len(parts) != 2:
                continue
            rank = {"ace": "A", "jack": "J", "queen": "Q", "king": "K"}.get(parts[0], parts[0])
            card = (rank, parts[1])
            image = pygame.image.load(path).convert_alpha()
            self.card_images[card] = pygame.transform.smoothscale(image, CARD_SIZE)

    def _load_chip_images(self) -> None:
        chip_root = self.asset_root.parent / "Card_Game_GFX" / "Chips"
        for value, color in zip(CHIP_VALUES, CHIP_COLORS):
            path = chip_root / f"chips_stacked_{color}.png"
            image = pygame.image.load(path).convert_alpha()
            self.chip_images[value] = pygame.transform.smoothscale(image, CHIP_SOURCE_SIZE)

    def _start_round_loading(self) -> None:
        if self.round_number >= POKER_ROUNDS:
            summary = self.tracker.summary()
            self.summary = summary
            PokerSessionTracker.print_session_summary(summary)
            self.phase = "summary"
            self.on_poker_session_complete(summary)
            return
        self.phase = "loading"
        self.loading_result = None
        self.loading_error = None
        next_round = self.round_number + 1
        hero_stack = self.player_state.chips

        def prepare() -> None:
            try:
                self.loading_result = self.generator.generate_round(next_round, hero_stack)
            except Exception as error:
                self.loading_error = error

        loading_thread = threading.Thread(target=prepare, daemon=True)
        self.loading_thread = loading_thread
        loading_thread.start()

    def update(self) -> None:
        self.poker_dealer.update()
        if (
            self.phase == "summary"
            and self.pending_rematch_at is not None
            and pygame.time.get_ticks() >= self.pending_rematch_at
        ):
            self.pending_rematch_at = None
            self.tracker = PokerSessionTracker()
            self.round_number = 0
            self.summary = None
            self.prepared = None
            self.record = None
            self.rematch_button = None
            self.results_layout_screen_size = None
            self.voice_session_number += 1
            self.voice_random.seed(self.voice_session_number)
            self.poker_dealer.reset()
            self.on_poker_session_start()
            self._start_round_loading()
            return

        if self.phase != "loading" or self.loading_thread is None or self.loading_thread.is_alive():
            return
        if self.loading_error is not None:
            raise self.loading_error
        if self.loading_result is None:
            raise RuntimeError("Poker scenario worker finished without a result")
        self.prepared = self.loading_result
        self.round_number += 1
        self.confidence_percent = None
        self.selected_action = None
        self.selected_amount = None
        self.selected_chips.clear()
        self.chip_rects = []
        self.selected_chip_rects = []
        self.record = None
        self.phase = "decision"
        self._layout_controls()
        if DEBUG_PRINT_POKER_BEST_MOVES:
            self._print_model_preferred_move()
        self.on_poker_round_start(self.round_number)

    def _print_model_preferred_move(self) -> None:
        assert self.prepared is not None
        evaluation = self.prepared.evaluation
        move = evaluation.best_action.upper()
        if evaluation.best_amount is not None:
            move += f" TO {evaluation.best_amount}"
        print(f"[POKER TEST] ROUND {self.round_number}/{POKER_ROUNDS} BEST MOVE: {move}")

    def handle_event(self, event: pygame.event.Event) -> str | None:
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.poker_dealer.reset()
            return "room"
        if self.phase == "loading":
            return None
        if self.phase == "result":
            if event.type == pygame.KEYDOWN and event.key in (pygame.K_RETURN, pygame.K_SPACE):
                self._start_round_loading()
            return None
        if self.phase == "summary":
            self._ensure_results_layout()
            now = pygame.time.get_ticks()
            if event.type == pygame.VIDEORESIZE:
                self._invalidate_results_layout()
                return None
            if event.type == pygame.MOUSEMOTION:
                self.results_last_mouse_pos = event.pos
                if self.rematch_button is not None:
                    was_selected = self.rematch_button.selected
                    self.rematch_button.selected = self.rematch_button.contains(event.pos)
                    if self.rematch_button.selected and not was_selected and self.menu_audio:
                        self.menu_audio.switch()
                return None
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if (
                    self.rematch_button is not None
                    and self.rematch_button.contains(event.pos)
                    and self.pending_rematch_at is None
                ):
                    self.rematch_button.selected = True
                    self.rematch_button.press(now)
                    if self.menu_audio:
                        self.menu_audio.click()
                    self.pending_rematch_at = now + MENU_PRESS_MS
                return None
            if event.type == pygame.KEYDOWN and event.key in (pygame.K_RETURN, pygame.K_SPACE):
                if self.pending_rematch_at is None and self.rematch_button is not None:
                    self.rematch_button.selected = True
                    self.rematch_button.press(now)
                    if self.menu_audio:
                        self.menu_audio.click()
                    self.pending_rematch_at = now + MENU_PRESS_MS
            return None
        if self.phase != "decision" or self.prepared is None:
            return None

        self._layout_controls()
        if event.type == pygame.MOUSEMOTION:
            if event.buttons[0] and CONFIDENCE_TRACK.inflate(16, 28).collidepoint(event.pos):
                self._set_confidence_from_mouse(event.pos[0])
            token = self._hover_at(event.pos)
            if token != self.hover_token and token is not None and self.menu_audio:
                self.menu_audio.switch()
            self.hover_token = token
            return None
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if CONFIDENCE_TRACK.inflate(16, 28).collidepoint(event.pos):
                self._set_confidence_from_mouse(event.pos[0])
                return None
            for rect, action in self.action_buttons:
                if rect.collidepoint(event.pos):
                    if self.menu_audio:
                        self.menu_audio.click()
                    self._select_action(action)
                    return None
            if self.selected_action in {"bet", "raise"}:
                for rect, value in self.chip_rects:
                    if rect.collidepoint(event.pos):
                        self._add_chip(value)
                        return None
                if self._remove_selected_chip(event.pos):
                    return None
            for rect, amount in self.size_buttons:
                if rect.collidepoint(event.pos) and self.selected_action in {"bet", "raise"}:
                    if self.menu_audio:
                        self.menu_audio.click()
                    self.selected_amount = amount
                    return None
            if self.lock_button_rect.collidepoint(event.pos) and self._decision_ready():
                if self.menu_audio:
                    self.menu_audio.click()
                self._lock_selected_decision()
                return None
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_HOME:
                self.confidence_percent = 0
            elif event.key == pygame.K_END:
                self.confidence_percent = 100
            elif event.key in (pygame.K_LEFT, pygame.K_RIGHT):
                if self.confidence_percent is None:
                    self.confidence_percent = 50
                else:
                    delta = -1 if event.key == pygame.K_LEFT else 1
                    self.confidence_percent = max(0, min(100, self.confidence_percent + delta))
            elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
                self._lock_selected_decision()
            else:
                shortcuts = {
                    pygame.K_f: "fold",
                    pygame.K_c: "call" if "call" in self.prepared.scenario.legal_actions else "check",
                    pygame.K_b: "bet",
                    pygame.K_r: "raise",
                }
                action = shortcuts.get(event.key)
                if action is not None and action in self.prepared.scenario.legal_actions:
                    self._select_action(action)
        return None

    def _add_chip(self, value: int) -> None:
        if self.prepared is None or self.selected_action not in {"bet", "raise"}:
            return
        maximum = self.prepared.scenario.effective_stack
        if sum(self.selected_chips) + value <= maximum:
            self.selected_chips.append(value)
            self.selected_amount = sum(self.selected_chips)

    def _remove_selected_chip(self, position: tuple[int, int]) -> bool:
        for rect, _value in self.selected_chip_rects:
            if rect.collidepoint(position):
                self.selected_chips.pop()
                self.selected_amount = sum(self.selected_chips) if self.selected_chips else None
                return True
        return False

    def _select_action(self, action: str) -> None:
        if self.prepared is None or action not in self.prepared.scenario.legal_actions:
            return
        if action != self.selected_action:
            self.selected_amount = None
            # Keep the action-selection helper usable by lightweight test
            # fixtures that construct a PokerGame without the chip widgets.
            selected_chips = getattr(self, "selected_chips", None)
            if selected_chips is not None:
                selected_chips.clear()
        self.selected_action = action
        if action not in {"bet", "raise"}:
            self.selected_amount = None
        self._layout_controls()

    def _decision_ready(self) -> bool:
        if self.prepared is None or self.confidence_percent is None or self.selected_action is None:
            return False
        if self.selected_action not in self.prepared.scenario.legal_actions:
            return False
        if self.selected_action == "bet":
            return self.selected_amount in self.prepared.scenario.candidate_bet_sizes
        if self.selected_action == "raise":
            return self.selected_amount in self.prepared.scenario.candidate_raise_sizes
        return self.selected_amount is None

    def _lock_selected_decision(self) -> None:
        if not self._decision_ready() or self.selected_action is None:
            return
        self._lock_decision(self.selected_action, self.selected_amount)

    def _lock_decision(self, action: str, amount: int | None) -> None:
        if self.phase != "decision" or self.prepared is None or self.confidence_percent is None:
            return
        if action not in {"bet", "raise"}:
            amount = None
        self._select_action(action)
        self.selected_amount = amount
        if not self._decision_ready():
            return
        record = self.tracker.lock_decision(
            self.prepared,
            self.round_number,
            action,
            amount,
            self.confidence_percent,
        )
        self.record = record
        self.phase = "result"
        self.on_poker_decision_locked(record)

    def _set_confidence_from_mouse(self, x: int) -> None:
        fraction = max(0.0, min(1.0, (x - CONFIDENCE_TRACK.left) / CONFIDENCE_TRACK.width))
        self.confidence_percent = max(0, min(100, round(fraction * 100)))

    def _layout_controls(self) -> None:
        if self.prepared is None:
            return
        legal = self.prepared.scenario.legal_actions
        button_width = 130
        gap = 14
        total_width = len(legal) * button_width + max(0, len(legal) - 1) * gap
        first_x = 565 + max(0, (680 - total_width) // 2)
        self.action_buttons = [
            (pygame.Rect(first_x + index * (button_width + gap), 520, button_width, 46), action)
            for index, action in enumerate(legal)
        ]
        self.size_buttons = []

    def _hover_at(self, position: tuple[int, int]) -> tuple[str, int | str] | None:
        for rect, action in self.action_buttons:
            if rect.collidepoint(position):
                return "action", action
        for rect, amount in self.size_buttons:
            if rect.collidepoint(position):
                return "size", amount
        if self._decision_ready() and self.lock_button_rect.collidepoint(position):
            return "lock", "decision"
        return None

    def draw(self) -> None:
        self.screen.fill("#063b2b")
        if self.phase == "loading":
            self._draw_loading()
        elif self.phase == "summary":
            self._draw_summary()
        elif self.prepared is not None:
            self._draw_scenario()

    def _draw_panel(self, rect: pygame.Rect) -> None:
        pygame.draw.rect(self.screen, "#082e24", rect, border_radius=16)
        pygame.draw.rect(self.screen, "#b88732", rect, width=2, border_radius=16)

    def _draw_loading(self) -> None:
        title = self.title_font.render("POKER DECISION TABLE", True, "#f7e9b9")
        self.screen.blit(title, title.get_rect(center=(640, 170)))
        text = self.font.render(
            f"Modeling opponent ranges and equity for round {self.round_number + 1}/{POKER_ROUNDS}...",
            True,
            "#ffffff",
        )
        self.screen.blit(text, text.get_rect(center=(640, 350)))
        self._text("The game remains responsive while the scenario is prepared.", (410, 395), 22, "#d8d0b8")
        self._text("ESC: return to casino floor", (35, 680), 20, "#d8d0b8")

    def _draw_scenario(self) -> None:
        assert self.prepared is not None
        scenario = self.prepared.scenario
        self._draw_panel(pygame.Rect(35, 88, 760, 350))
        self._draw_panel(pygame.Rect(820, 88, 425, 350))
        self._draw_panel(pygame.Rect(35, 450, 500, 220))
        self._draw_panel(pygame.Rect(550, 450, 695, 220))
        title = self.title_font.render("POKER DECISION TABLE", True, "#f7e9b9")
        self.screen.blit(title, title.get_rect(center=(640, 38)))
        self._text(f"ROUND {self.round_number}/{POKER_ROUNDS}", (1050, 38), 22, "#f1d277")
        self._text(f"{scenario.street.upper()}  •  YOU: {scenario.hero_position}", (60, 112), 24, "#f1d277")
        self._text(
            f"Your stack ${scenario.hero_stack}   Pot ${scenario.pot}   To call ${scenario.amount_to_call}   "
            f"Min raise-to ${scenario.minimum_raise_to}",
            (60, 145),
            22,
        )

        self._text("YOUR HAND", (60, 185), 22, "#f1d277")
        for index, card in enumerate(scenario.hero_cards):
            self._draw_card(card, (60 + index * 92, 220))
        self._text("BOARD", (310, 185), 22, "#f1d277")
        if scenario.board:
            for index, card in enumerate(scenario.board):
                self._draw_card(card, (310 + index * 92, 220))
        else:
            self._text("No community cards yet", (310, 240), 20, "#b9ad8f")

        self._text("PLAYERS", (850, 115), 22, "#f1d277")
        for index, row in enumerate(build_table_rows(scenario, self.record)):
            color = "#f1d277" if row.is_you else "#777777" if row.state == "FOLDED" else "#ffffff"
            status = row.status_text
            if len(status) > 34:
                status = status[:31] + "..."
            self._text(
                f"{row.position:<3} ${row.stack:>4}  {status}",
                (850, 150 + index * 23),
                15,
                color,
            )
        self._text("ACTION HISTORY", (850, 320), 20, "#f1d277")
        history_lines = [action.describe() for action in scenario.action_history]
        if self.record is not None:
            history_lines = [action.describe() for action in self.record.final_action_history]
        else:
            history_lines.append("-> YOU to act")
        history_font = serif_font(14)
        history_clip = pygame.Rect(840, 340, 390, 92)
        previous_clip = self.screen.get_clip()
        self.screen.set_clip(history_clip)
        for index, line in enumerate(history_lines[-6:]):
            while len(line) > 1 and history_font.size(line)[0] > history_clip.width:
                line = line[:-1]
            self.screen.blit(history_font.render(line, True, "#d8d0b8"), (850, 342 + index * 15))
        self.screen.set_clip(previous_clip)

        if self.phase == "result" and self.record is not None:
            self._draw_recorded_result()
            return

        self._text("CONFIDENCE", (60, 475), 22, "#f1d277")
        self._text("How confident are you in this decision?", (60, 505), 18, "#d8d0b8")
        self._text("This measures decision quality, not luck.", (60, 530), 17, "#b9ad8f")
        pygame.draw.rect(self.screen, "#3b2418", CONFIDENCE_TRACK, border_radius=7)
        pygame.draw.rect(self.screen, "#b88732", CONFIDENCE_TRACK, width=2, border_radius=7)
        if self.confidence_percent is not None:
            marker = CONFIDENCE_TRACK.left + round(self.confidence_percent * CONFIDENCE_TRACK.width / 100)
            pygame.draw.circle(self.screen, "#f1d277", (marker, CONFIDENCE_TRACK.centery), 11)
            confidence = f"{self.confidence_percent}%"
        else:
            confidence = "UNSET - click or move slider"
        self._text("0%", (70, 582), 17, "#d8d0b8")
        self._text("100%", (455, 582), 17, "#d8d0b8")
        self._text(confidence, (190, 615), 22, "#f1d277")

        self._text("BETTING", (575, 475), 22, "#f1d277")
        for rect, action in self.action_buttons:
            self._draw_button(
                rect,
                self._action_label(action),
                self.hover_token == ("action", action),
                selected=self.selected_action == action,
            )
        if self.selected_action in {"bet", "raise"}:
            self._draw_chip_controls()
        self._draw_button(
            self.lock_button_rect,
            "LOCK DECISION",
            self.hover_token == ("lock", "decision"),
            enabled=self._decision_ready(),
        )
        if not self._decision_ready():
            if self.confidence_percent is None:
                guidance = "Select confidence before locking"
            elif self.selected_action is None:
                guidance = "Choose one legal action"
            else:
                guidance = f"Choose a valid {self.selected_action} size"
            if self.selected_action not in {"bet", "raise"}:
                self._text(guidance, (800, 568), 14, "#b9ad8f")
        self._text("ESC: return to casino floor", (35, 680), 20, "#d8d0b8")

    def _draw_chip_controls(self) -> None:
        assert self.prepared is not None
        self.chip_rects = []
        self._text(f"WAGER (1-${self.prepared.scenario.hero_stack})", (800, 470), 20, "#f1d277")
        self._text("CLICK CHIPS TO BUILD YOUR WAGER", (800, 495), 16, "#d8d0b8")
        sizes = self._available_sizes()
        if sizes:
            label = "RAISE TO:" if self.selected_action == "raise" else "BET TO:"
            options = "  ".join(f"${amount}" for amount in sizes)
            self._text(f"{label} {options}", (800, 568), 14, "#f1d277")
        origin_x, origin_y = CHIP_TRAY_ORIGIN
        step_x, step_y = CHIP_TRAY_STEP
        remaining = self.prepared.scenario.effective_stack - sum(self.selected_chips)
        for row in range(2):
            for column, (value, color) in enumerate(
                zip(CHIP_VALUES[row * 3:(row + 1) * 3], CHIP_COLORS[row * 3:(row + 1) * 3])
            ):
                rect = pygame.Rect(
                    origin_x + column * step_x,
                    origin_y + row * step_y,
                    *CHIP_DISPLAY_SIZE,
                )
                self.chip_rects.append((rect, value))
                chip = pygame.transform.smoothscale(self.chip_images[value], CHIP_DISPLAY_SIZE)
                if value > remaining:
                    chip = chip.copy()
                    chip.set_alpha(80)
                self.screen.blit(chip, rect)
                self._text(f"${value}", (rect.x + 42, rect.y + 8), 17, "#f1d277")

        pygame.draw.rect(self.screen, "#24170f", WAGER_FIELD, border_radius=8)
        pygame.draw.rect(self.screen, "#b88732", WAGER_FIELD, width=2, border_radius=8)
        self._draw_selected_chips()
        amount = self.selected_amount if self.selected_amount is not None else "_"
        wager = self.font.render(f"${amount}", True, "#f1d277")
        self.screen.blit(wager, wager.get_rect(center=(WAGER_FIELD.centerx + 14, WAGER_FIELD.centery)))
        if self.selected_chips and self.selected_amount not in self._available_sizes():
            self._text("Choose a modeled total", (800, 635), 16, "#b9ad8f")

    def _available_sizes(self) -> tuple[int, ...]:
        if self.prepared is None:
            return ()
        if self.selected_action == "bet":
            return self.prepared.scenario.player_candidate_bet_sizes
        if self.selected_action == "raise":
            return self.prepared.scenario.player_candidate_raise_sizes
        return ()

    def _draw_selected_chips(self) -> None:
        self.selected_chip_rects = []
        if not self.selected_chips:
            return
        base = pygame.Rect(WAGER_FIELD.left + 6, WAGER_FIELD.top + 6, 30, 30)
        visible = min(len(self.selected_chips), 8)
        click_rect = base.move(0, -(visible - 1) * 2)
        click_rect.height += (visible - 1) * 2
        self.selected_chip_rects.append((click_rect, self.selected_chips[-1]))
        for index, value in enumerate(self.selected_chips[-visible:]):
            chip = pygame.transform.smoothscale(self.chip_images[value], base.size)
            self.screen.blit(chip, base.move(0, -index * 2))

    def _draw_recorded_result(self) -> None:
        assert self.record is not None
        panel = pygame.Rect(300, 480, 680, 170)
        pygame.draw.rect(self.screen, "#21130f", panel, border_radius=12)
        pygame.draw.rect(self.screen, "#d29a32", panel, width=3, border_radius=12)
        self._text("DECISION RECORDED", (505, 500), 31, "#f1d277")
        amount = f" to ${self.record.player_amount}" if self.record.player_action in {"bet", "raise"} else ""
        self._text(
            f"{self.record.player_action.upper()}{amount}   |   confidence {self.record.confidence_percent}%",
            (425, 545),
            24,
            "#ffffff",
        )
        self._text("No model answer is shown during the five-round assessment.", (390, 585), 20, "#d8d0b8")
        prompt = "ENTER: session report" if self.round_number == POKER_ROUNDS else "ENTER: next independent scenario"
        self._text(prompt, (485, 620), 20, "#f1d277")

    def _invalidate_results_layout(self) -> None:
        self.results_layout_screen_size = None

    @staticmethod
    def _wrap_result_text(text: str, font: pygame.font.Font, max_width: int) -> list[str]:
        words = str(text).split()
        if not words:
            return []
        lines: list[str] = []
        current = words[0]
        for word in words[1:]:
            candidate = f"{current} {word}"
            if font.size(candidate)[0] <= max_width:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
        return lines

    def _build_results_layout(
        self,
        *,
        body_reduction: int,
        gap_scale: float,
        observation_count: int,
        show_confidence: bool,
    ):
        """Create result surfaces from the final displayed paper rect only."""
        paper_rect = self.results_paper_rect
        safe_rect = self.results_safe_rect
        ph = paper_rect.height
        cx = safe_rect.centerx
        summary = self.summary or {}

        title_font = serif_font(max(16, int(ph * 0.040)))
        score_label_font = serif_font(max(12, int(ph * 0.027)))
        score_value_font = serif_font(max(25, int(ph * 0.060)))
        section_font = serif_font(max(11, int(ph * 0.025) - body_reduction))
        body_font = serif_font(max(10, int(ph * 0.020) - body_reduction))
        small_font = serif_font(max(9, int(ph * 0.016) - body_reduction))
        heading_color = (86, 20, 30)
        body_color = (45, 27, 22)
        score_color = (112, 24, 28)
        line_gap = max(1, int(ph * 0.004 * gap_scale))
        section_gap = max(4, int(ph * 0.012 * gap_scale))
        block_gap = max(6, int(ph * 0.018 * gap_scale))

        button_height = max(28, int(ph * 0.052))
        # Leave room for MenuButton's hover/press expansion and ornaments.
        button_width = min(int(safe_rect.width * 0.78), safe_rect.width)
        button_bottom = min(
            safe_rect.bottom - max(2, int(ph * 0.008)),
            paper_rect.top + int(ph * 0.84),
        )
        button_rect = pygame.Rect(0, 0, button_width, button_height)
        button_rect.midbottom = (cx, button_bottom)
        content_bottom = button_rect.top - max(5, int(ph * 0.018))

        items: list[tuple[pygame.Surface, pygame.Rect]] = []
        element_rects: list[pygame.Rect] = []
        cursor_y = safe_rect.top

        def add_block(
            text: str,
            font: pygame.font.Font,
            color=body_color,
            gap_after: int = block_gap,
            max_lines: int | None = None,
        ) -> None:
            nonlocal cursor_y
            lines: list[str] = []
            for paragraph in str(text).split("\n"):
                lines.extend(self._wrap_result_text(paragraph, font, int(safe_rect.width * 0.92)))
            if max_lines is not None:
                lines = lines[:max_lines]
            if not lines:
                cursor_y += gap_after
                return
            for line in lines:
                surface = font.render(line, True, color)
                rect = surface.get_rect(midtop=(cx, cursor_y))
                items.append((surface, rect))
                element_rects.append(rect)
                cursor_y = rect.bottom + line_gap
            cursor_y += gap_after

        add_block("THE HOUSE SAYS", title_font, heading_color, gap_after=section_gap)
        add_block("DECISION QUALITY", section_font, heading_color, gap_after=section_gap)
        reasonable = int(summary.get("reasonable_decision_count", summary.get("preferred_action_count", 0)))
        rounds = int(summary.get("rounds", POKER_ROUNDS))
        close = int(summary.get("close_decision_count", 0))
        # Only show a clear-mistake count when the tracker explicitly classified it.
        # Inferring it as rounds minus reasonable would mislabel close decisions.
        clear = int(summary.get("clear_mistake_count", 0))
        add_block(f"{reasonable} / {rounds} reasonable decisions", body_font, gap_after=line_gap)
        if close:
            noun = "decision" if close == 1 else "decisions"
            add_block(f"{close} close {noun}", body_font, gap_after=line_gap)
        if clear:
            noun = "mistake" if clear == 1 else "mistakes"
            add_block(f"{clear} clear {noun}", body_font, gap_after=block_gap)

        observations = list(summary.get("observations", []))[:observation_count]
        if not observations:
            observations = [
                "Your decisions were generally reasonable, with only small differences from the model's preferred lines."
            ]
        add_block("WHAT THE HOUSE NOTICED", section_font, heading_color, gap_after=section_gap)
        for observation in observations:
            add_block(observation, body_font, gap_after=section_gap, max_lines=3)

        confidence_insight = summary.get("confidence_insight")
        if show_confidence and confidence_insight:
            add_block("CONFIDENCE CHECK", section_font, heading_color, gap_after=section_gap)
            add_block(confidence_insight, body_font, gap_after=block_gap, max_lines=3)

        add_block(
            "Five decisions are a small sample.\nThis is model-based feedback, not GTO truth.",
            small_font,
            body_color,
            gap_after=0,
            max_lines=2,
        )

        if cursor_y > content_bottom:
            return None

        element_rects.append(button_rect)
        if any(previous.bottom >= current.top for previous, current in zip(element_rects, element_rects[1:])):
            return None
        if any(not safe_rect.contains(rect) for rect in element_rects):
            return None
        button_visual_rect = button_rect.inflate(
            max(2, int(button_rect.width * 0.10)),
            max(2, int(button_rect.height * 0.10)),
        )
        if not safe_rect.contains(button_visual_rect):
            return None
        return items, element_rects, button_rect

    def _ensure_results_layout(self) -> None:
        screen_size = self.screen.get_size()
        if self.results_layout_screen_size == screen_size and self.rematch_button is not None:
            return

        source = self.results_paper_source
        max_width = max(1, int(self.screen.get_width() * 0.86))
        max_height = max(1, int(self.screen.get_height() * 0.94))
        scale = min(max_width / source.get_width(), max_height / source.get_height())
        paper_size = (
            max(1, int(source.get_width() * scale)),
            max(1, int(source.get_height() * scale)),
        )
        self.results_paper_surface = pygame.transform.smoothscale(source, paper_size)
        self.results_paper_rect = self.results_paper_surface.get_rect(center=self.screen.get_rect().center)
        px, py = self.results_paper_rect.topleft
        pw, ph = self.results_paper_rect.size
        self.results_safe_rect = pygame.Rect(
            px + int(pw * 0.13),
            py + int(ph * 0.13),
            int(pw * 0.74),
            int(ph * 0.73),
        )

        layout = None
        for reduction, gap_scale, observation_count, show_confidence in (
            (0, 1.0, 2, True),
            (1, 0.85, 2, True),
            (2, 0.70, 2, True),
            (2, 0.60, 1, True),
            (3, 0.50, 1, False),
            (4, 0.40, 1, False),
        ):
            layout = self._build_results_layout(
                body_reduction=reduction,
                gap_scale=gap_scale,
                observation_count=observation_count,
                show_confidence=show_confidence,
            )
            if layout is not None:
                break
        if layout is None:
            raise AssertionError("Poker results content does not fit inside the paper safe area")

        self.result_draw_items, self.result_element_rects, button_rect = layout
        button_face = serif_font(max(13, min(24, int(self.results_paper_rect.height * 0.026))), True)
        self.rematch_button = MenuButton("CARE TO PROVE ME WRONG?", 0, button_face, button_rect)
        self.rematch_button.selected = self.rematch_button.contains(self.results_last_mouse_pos)
        self.results_layout_screen_size = screen_size

    def _draw_summary(self) -> None:
        self._ensure_results_layout()
        self.screen.fill((7, 3, 4))
        self.screen.blit(self.results_paper_surface, self.results_paper_rect)
        for surface, rect in self.result_draw_items:
            self.screen.blit(surface, rect)
        self.rematch_button.draw(self.screen, pygame.time.get_ticks())

        # Raw EV instrumentation stays in the console/debug report.
        if DEBUG_POKER_RESULTS_LAYOUT:
            pygame.draw.rect(self.screen, (0, 255, 0), self.results_paper_rect, 2)
            pygame.draw.rect(self.screen, (0, 180, 255), self.results_safe_rect, 2)
            for rect in self.result_element_rects:
                pygame.draw.rect(self.screen, (255, 255, 0), rect, 1)

    def _draw_card(self, card: Card, position: tuple[int, int]) -> None:
        image = self.card_images.get(card)
        if image is not None:
            self.screen.blit(image, position)
            return
        rect = pygame.Rect(position, CARD_SIZE)
        pygame.draw.rect(self.screen, "#f6f1df", rect, border_radius=7)
        pygame.draw.rect(self.screen, "#24170f", rect, width=2, border_radius=7)
        self._text(card_code(card), (rect.x + 10, rect.y + 10), 22, "#24170f")

    def _draw_button(
        self,
        rect: pygame.Rect,
        label: str,
        hovered: bool,
        small: bool = False,
        enabled: bool = True,
        selected: bool = False,
    ) -> None:
        fill = (
            "#8a652b" if enabled and selected
            else "#6d5128" if enabled and hovered
            else "#4e351d" if enabled
            else "#3e3e3e"
        )
        border = "#f1d277" if enabled else "#777777"
        pygame.draw.rect(self.screen, fill, rect, border_radius=7)
        pygame.draw.rect(self.screen, border, rect, width=2, border_radius=7)
        font = self.small_font if small else self.font
        surface = font.render(label, True, "#ffffff" if enabled else "#999999")
        self.screen.blit(surface, surface.get_rect(center=rect.center))

    def _action_label(self, action: str) -> str:
        assert self.prepared is not None
        if action == "call":
            return f"CALL ${self.prepared.scenario.amount_to_call}"
        return action.upper()

    def _size_label(self, amount: int) -> str:
        assert self.prepared is not None
        maximum = self.prepared.scenario.hero_contribution + self.prepared.scenario.hero_stack
        return "ALL-IN" if amount == maximum else f"${amount}"

    def _text(self, text: str, position: tuple[int, int], size: int, color: str = "#ffffff") -> None:
        self.screen.blit(serif_font(size).render(text, True, color), position)

    def on_poker_session_start(self) -> None:
        if not hasattr(self, "poker_dealer"):
            return
        context = self._voice_context("entry")
        self.poker_dealer.clear_context(context, include_high=True, stop_current=True)
        self.poker_dealer.play_line("poker_intro", HIGH, context=context)

    def on_poker_round_start(self, round_index: int) -> None:
        if not hasattr(self, "poker_dealer"):
            return
        context = self._voice_context(f"round:{round_index}")
        self.poker_dealer.clear_context(context)
        if round_index == POKER_ROUNDS:
            self.poker_dealer.play_line("poker_final_round", HIGH, context=context)
            return
        if self.voice_random.random() < 0.40:
            self.poker_dealer.play_line(
                self.voice_random.choice(("poker_round_1", "poker_round_2", "poker_round_3")),
                LOW,
                context=context,
            )

    def on_poker_decision_locked(self, record: PokerDecisionRecord) -> None:
        if not hasattr(self, "poker_dealer") or not hasattr(self, "voice_random"):
            return
        if self.voice_random.random() >= 0.45:
            return
        context = self._voice_context(f"round:{record.round_number}")
        if record.confidence_percent >= 80 and self.voice_random.random() < 0.55:
            reaction = "poker_reaction_4"
        else:
            reaction = self.voice_random.choice(
                ("poker_reaction_1", "poker_reaction_2", "poker_reaction_3")
            )
        self.poker_dealer.play_line(reaction, LOW, context=context)

    def on_poker_session_complete(self, summary: dict) -> None:
        if not hasattr(self, "poker_dealer"):
            return
        context = self._voice_context("results")
        # Results supersede any stale round/final-round chatter.
        self.poker_dealer.clear_context(context, include_high=True, stop_current=True)
        self.poker_dealer.play_line("poker_results", HIGH, context=context)

    def _voice_context(self, stage: str) -> str:
        return f"poker:{self.voice_session_number}:{stage}"
