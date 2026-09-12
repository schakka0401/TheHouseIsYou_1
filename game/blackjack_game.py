"""Integrated blackjack table: friend's hand flow with the decision experiment layered on top."""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import random
import threading

import pygame

from game.bankroll_simulator import simulate_long_term_bankroll
from game.blackjack_engine import BlackjackEngine, Scenario, hand_value
from game.decision_tracker import DecisionRecord, DecisionTracker, confidence_probability
from game.player_state import PlayerState

BLACKJACK_SESSION_ROUNDS = 15
BANKROLL_SIMULATIONS = 10_000
BANKROLL_HORIZON = 100
CHIP_VALUES = (1, 5, 10, 25, 50, 100)
CHIP_COLORS = ("white", "red", "blue", "green", "black", "purple")
CHIP_SIZE = (54, 54)
WAGER_CHIP_SIZE = (44, 44)
BET_CHIP_SIZE = (40, 40)


class BlackjackGame:
    """A responsive blackjack hand loop with confidence and wager checkpoints."""

    def __init__(self, screen: pygame.Surface, player_state: PlayerState, seed: int | None = None, simulations: int = 50_000):
        self.screen = screen
        self.player_state = player_state
        self.initial_bankroll = player_state.chips
        self.engine = BlackjackEngine(seed=seed, simulations=simulations)
        self.random = random.Random(seed)
        self.tracker = DecisionTracker()
        self.round_number = 0
        self.used_scenarios: set[tuple] = set()
        targets = ["EASY"] * 2 + ["MEDIUM"] * 9 + ["HARD"] * 4
        self.random.shuffle(targets)
        self.targets = targets
        self.phase = "decision"
        self.scenario: Scenario | None = None
        self.player_hand = []
        self.dealer_hand = []
        self.round_deck = []
        self.current_hand_records: list[DecisionRecord] = []
        self.hand_bankroll_before = player_state.chips
        self.current_bet = 0
        self.confidence_level: int | None = None
        self.confidence_selected = False
        self.wager_text = ""
        self.valid_bet_selected = False
        self.profile = None
        self.bankroll_projection = None
        self.analysis_thread: threading.Thread | None = None
        self.analysis_result = None
        self.analysis_error: Exception | None = None
        self.analysis_completed = 0
        self.analysis_total = 0
        self.card_images: dict[tuple[str, str], pygame.Surface] = {}
        self.chip_images: dict[tuple[str, str], pygame.Surface] = {}
        self.chip_rects: list[tuple[pygame.Rect, int]] = []
        self.selected_chips: list[int] = []
        self.selected_chip_rects: list[tuple[pygame.Rect, int]] = []
        self.title_font = pygame.font.Font(None, 42)
        self.font = pygame.font.Font(None, 27)
        self.small_font = pygame.font.Font(None, 22)
        self._load_card_images()
        self._load_chip_images()
        self._queue_round()

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
            image = pygame.image.load(path).convert_alpha()
            self.card_images[(rank, parts[1])] = pygame.transform.smoothscale(image, (105, 147))

    def _load_chip_images(self) -> None:
        chip_root = Path(__file__).resolve().parents[1] / "static" / "assets" / "Card_Game_GFX" / "Chips"
        for color in CHIP_COLORS:
            for style in ("stacked", "flat"):
                path = chip_root / f"chips_{style}_{color}.png"
                image = pygame.image.load(path).convert_alpha()
                self.chip_images[(style, color)] = pygame.transform.smoothscale(image, CHIP_SIZE)

    def _queue_round(self) -> None:
        if self.round_number >= BLACKJACK_SESSION_ROUNDS or self.player_state.chips <= 0:
            self._finish_session()
            return
        target = self.targets[self.round_number] if self.round_number < len(self.targets) else None
        self.scenario = self.engine.generate_raw_scenario(self.used_scenarios, target)
        self.used_scenarios.add(self.scenario.key)
        self.round_number += 1
        visible = list(self.scenario.player_cards) + [self.scenario.dealer_upcard]
        self.round_deck = [card for card in self.engine.deck() if card not in visible]
        self.engine.random.shuffle(self.round_deck)
        self.player_hand = list(self.scenario.player_cards)
        self.dealer_hand = [self.scenario.dealer_upcard, self.round_deck.pop()]
        self.current_hand_records = []
        self.hand_bankroll_before = self.player_state.chips
        self.current_bet = 0
        self._reset_decision_input()
        self.phase = "confidence"

    def _reset_decision_input(self) -> None:
        self.confidence_level = None
        self.confidence_selected = False
        self.wager_text = ""
        self.valid_bet_selected = False
        self.selected_chips.clear()

    def _valid_wager(self) -> bool:
        try:
            amount = int(self.wager_text)
        except (TypeError, ValueError):
            return False
        return 1 <= amount <= self.player_state.chips

    def _set_chip_wager(self, value: int) -> None:
        if sum(self.selected_chips) + value <= self.player_state.chips:
            self.selected_chips.append(value)
            self.wager_text = str(sum(self.selected_chips))

    def _remove_selected_chip(self, position: tuple[int, int]) -> bool:
        for rect, value in self.selected_chip_rects:
            if rect.collidepoint(position):
                self.selected_chips.remove(value)
                self.wager_text = str(sum(self.selected_chips)) if self.selected_chips else ""
                return True
        return False

    def _finish_session(self) -> None:
        if self.phase in {"analyzing", "results"}:
            return
        self.phase = "analyzing"
        self.analysis_completed = 0
        self.analysis_total = len(self.tracker.records)
        self.analysis_result = None
        self.analysis_error = None

        def analyze_session() -> None:
            try:
                profile = self.tracker.analyze(self.engine, self._analysis_progress)
                projection = simulate_long_term_bankroll(self.tracker.records, self.engine, self.initial_bankroll, simulations=BANKROLL_SIMULATIONS, horizon=BANKROLL_HORIZON)
                self.analysis_result = (profile, projection)
            except Exception as error:
                self.analysis_error = error

        self.analysis_thread = threading.Thread(target=analyze_session, daemon=True)
        self.analysis_thread.start()

    def _analysis_progress(self, completed: int, total: int) -> None:
        self.analysis_completed = completed
        self.analysis_total = total

    def update(self) -> None:
        if self.phase == "analyzing" and self.analysis_thread is not None and not self.analysis_thread.is_alive():
            if self.analysis_error:
                raise self.analysis_error
            self.profile, self.bankroll_projection = self.analysis_result
            self.phase = "results"

    def _record_action(self, action: str) -> DecisionRecord:
        assert self.scenario is not None and self.confidence_level is not None
        total, _ = hand_value(self.player_hand)
        record = DecisionRecord(
            round_number=self.round_number,
            player_cards=[f"{rank} of {suit}" for rank, suit in self.player_hand],
            player_total=total,
            dealer_upcard=f"{self.scenario.dealer_upcard[0]} of {self.scenario.dealer_upcard[1]}",
            player_action=action,
            confidence_level=self.confidence_level,
            confidence_probability=confidence_probability(self.confidence_level),
            bet=self.current_bet,
            bankroll_before=self.hand_bankroll_before,
            bankroll_after=self.player_state.chips,
            actual_round_result="pending",
            scenario=Scenario(tuple(self.player_hand), self.scenario.dealer_upcard),
        )
        self.tracker.add(record)
        self.current_hand_records.append(record)
        return record

    def _settle_hand(self, result: str) -> None:
        if result == "win":
            self.player_state.chips += self.current_bet
        elif result == "loss":
            self.player_state.chips -= self.current_bet
        for record in self.current_hand_records:
            record.actual_round_result = result
            record.bankroll_after = self.player_state.chips
        self.phase = "result"

    def _stand(self) -> None:
        while hand_value(self.dealer_hand)[0] < 17:
            self.dealer_hand.append(self.round_deck.pop())
        player_total, _ = hand_value(self.player_hand)
        dealer_total, _ = hand_value(self.dealer_hand)
        if dealer_total > 21 or player_total > dealer_total:
            result = "win"
        elif player_total < dealer_total:
            result = "loss"
        else:
            result = "push"
        self._settle_hand(result)

    def _take_action(self, action: str) -> None:
        if self.phase != "decision" or not self.confidence_selected or not self.valid_bet_selected:
            return
        self._record_action(action)
        if action == "stand":
            self._stand()
            return
        self.player_hand.append(self.round_deck.pop())
        total, _ = hand_value(self.player_hand)
        if total > 21:
            self._settle_hand("loss")
        else:
            self.scenario = Scenario(tuple(self.player_hand), self.scenario.dealer_upcard)
            self.confidence_level = None
            self.confidence_selected = False
            self.phase = "confidence"

    def handle_event(self, event: pygame.event.Event) -> str | None:
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            return "room"
        if self.phase in {"analyzing", "loading"}:
            return None

        if self.phase == "confidence":
            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_LEFT, pygame.K_DOWN):
                    self.confidence_level = max(1, (self.confidence_level or 1) - 1)
                    self.confidence_selected = True
                elif event.key in (pygame.K_RIGHT, pygame.K_UP):
                    self.confidence_level = min(10, (self.confidence_level or 1) + 1)
                    self.confidence_selected = True
                elif pygame.K_1 <= event.key <= pygame.K_9:
                    self.confidence_level = event.key - pygame.K_0
                    self.confidence_selected = True
                elif event.key == pygame.K_0:
                    self.confidence_level = 10
                    self.confidence_selected = True
                elif event.key in (pygame.K_RETURN, pygame.K_SPACE) and self.confidence_selected:
                    self.phase = "decision" if self.current_bet else "wager"
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                self._set_confidence_from_mouse(event.pos[0])
            elif event.type == pygame.MOUSEMOTION and event.buttons[0]:
                self._set_confidence_from_mouse(event.pos[0])
            return None

        if self.phase == "wager":
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self._remove_selected_chip(event.pos):
                    return None
                for rect, value in self.chip_rects:
                    if rect.collidepoint(event.pos):
                        self._set_chip_wager(value)
                        return None
            if event.type == pygame.KEYDOWN:
                if pygame.K_0 <= event.key <= pygame.K_9 and len(self.wager_text) < 6:
                    self.selected_chips.clear()
                    self.wager_text += str(event.key - pygame.K_0)
                elif event.key == pygame.K_BACKSPACE:
                    self.selected_chips.clear()
                    self.wager_text = self.wager_text[:-1]
                elif event.key == pygame.K_UP:
                    self.selected_chips.clear()
                    self.wager_text = str(min(self.player_state.chips, max(1, int(self.wager_text or "0") + 1)))
                elif event.key == pygame.K_DOWN:
                    self.selected_chips.clear()
                    self.wager_text = str(max(1, int(self.wager_text or "1") - 1))
                elif event.key in (pygame.K_RETURN, pygame.K_SPACE) and self._valid_wager():
                    self.current_bet = int(self.wager_text)
                    self.valid_bet_selected = True
                    self.phase = "decision"
            return None

        if self.phase == "decision":
            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_h, pygame.K_LEFT):
                    self._take_action("hit")
                elif event.key in (pygame.K_s, pygame.K_RIGHT):
                    self._take_action("stand")
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if pygame.Rect(285, 570, 220, 55).collidepoint(event.pos):
                    self._take_action("hit")
                elif pygame.Rect(530, 570, 220, 55).collidepoint(event.pos):
                    self._take_action("stand")
            return None

        if self.phase == "result" and event.type == pygame.KEYDOWN and event.key in (pygame.K_RETURN, pygame.K_SPACE):
            if self.round_number >= BLACKJACK_SESSION_ROUNDS or self.player_state.chips <= 0:
                self._finish_session()
            else:
                self._queue_round()
        elif self.phase == "results" and event.type == pygame.KEYDOWN and event.key in (pygame.K_RETURN, pygame.K_SPACE):
            if self.player_state.chips > 0:
                self.__init__(self.screen, self.player_state)
            else:
                return "room"
        return None

    def _set_confidence_from_mouse(self, x: int) -> None:
        fraction = max(0.0, min(1.0, (x - 300) / 500))
        self.confidence_level = max(1, min(10, round(1 + fraction * 9)))
        self.confidence_selected = True

    def _text(self, text, position, size=27, color=(245, 233, 190)):
        self.screen.blit(pygame.font.Font(None, size).render(text, True, color), position)

    def _draw_card(self, card, position, hidden=False):
        if hidden:
            pygame.draw.rect(self.screen, "#8b2020", (*position, 105, 147), border_radius=8)
            pygame.draw.rect(self.screen, "#f7e9b9", (*position, 105, 147), width=2, border_radius=8)
        elif card in self.card_images:
            self.screen.blit(self.card_images[card], position)

    def _draw_hands(self):
        dealer_hidden = self.phase not in {"result", "analyzing", "results"}
        dealer_x = max(35, 640 - len(self.dealer_hand) * 60)
        for index, card in enumerate(self.dealer_hand):
            self._draw_card(card, (dealer_x + index * 120, 65), hidden=dealer_hidden and index == 1)
        player_x = max(35, 640 - len(self.player_hand) * 60)
        for index, card in enumerate(self.player_hand):
            self._draw_card(card, (player_x + index * 120, 280))

    def draw(self):
        self.screen.fill("#154734")
        if self.phase == "analyzing":
            self.screen.blit(self.title_font.render("ANALYZING YOUR DECISIONS...", True, "#f7e9b9"), (35, 25))
            completed, total = self.analysis_completed, max(1, self.analysis_total)
            self._text("Running decision simulations...", (350, 330), 31, "#f1d277")
            self._text(f"Analyzing decision {completed} / {total}", (430, 385), 27)
            pygame.draw.rect(self.screen, "#3b2418", (310, 440, 660, 26), border_radius=10)
            pygame.draw.rect(self.screen, "#d29a32", (310, 440, int(660 * completed / total), 26), border_radius=10)
            return
        if self.phase == "results":
            self._draw_results()
            return

        self.screen.blit(self.title_font.render("BLACKJACK DECISION TABLE", True, "#f7e9b9"), (35, 25))
        self._text(f"Hand {self.round_number}/{BLACKJACK_SESSION_ROUNDS}", (990, 35))
        self._text(f"Shared bankroll: {self.player_state.chips} chips", (35, 80))
        self._draw_hands()
        player_total, _ = hand_value(self.player_hand)
        dealer_total, _ = hand_value(self.dealer_hand)
        self._text(f"DEALER: {'?' if self.phase != 'result' else dealer_total}", (50, 235), 29)
        self._text(f"YOUR HAND: {player_total}", (50, 465), 29)
        if self.phase == "confidence":
            self._text("Set confidence before choosing an action (1–10)", (300, 500), 25)
            pygame.draw.rect(self.screen, "#3b2418", (300, 535, 500, 14), border_radius=7)
            if self.confidence_selected:
                marker = 300 + int((self.confidence_level - 1) * 500 / 9)
                pygame.draw.circle(self.screen, "#f1d277", (marker, 542), 12)
                self._text(f"Confidence: {self.confidence_level}/10 ({confidence_probability(self.confidence_level):.0%})", (420, 555), 24, "#f1d277")
            else:
                self._text("Move the slider or press 1–10 to select", (390, 555), 22, "#d8d0b8")
        elif self.phase == "wager":
            self._text("Enter a valid wager (1 to your bankroll), then press ENTER", (220, 520), 24)
            self._text(f"Wager: {self.wager_text or '_'} chips", (500, 570), 34, "#f1d277")
            if self.selected_chips:
                self._text("Click a placed chip to remove it", (350, 595), 19, "#d8d0b8")
            self._draw_selected_chips(start_x=820, start_y=455)
            self._draw_wager_chips()
        elif self.phase == "decision":
            self._text(f"Confidence locked: {self.confidence_level}/10   Wager locked: {self.current_bet} chips", (270, 515), 23, "#f1d277")
            self._draw_selected_chip()
            pygame.draw.rect(self.screen, "#286db2", (285, 570, 220, 55), border_radius=8)
            pygame.draw.rect(self.screen, "#b52f38", (530, 570, 220, 55), border_radius=8)
            self._text("♠  HIT  ♥", (345, 585), 27)
            self._text("♦  STAND  ♣", (565, 585), 27)
        elif self.phase == "result":
            result = self.current_hand_records[-1].actual_round_result.upper()
            self._text(f"RESULT: {result}", (500, 520), 32, "#f1d277")
            self._text("Press ENTER for the next hand", (425, 575), 25)
        self._text("ESC: return to room", (35, 680), 22, "#d8d0b8")

    def _draw_wager_chips(self) -> None:
        self.chip_rects = []
        x = 300
        y = 610
        for index, (value, color) in enumerate(zip(CHIP_VALUES, CHIP_COLORS)):
            rect = pygame.Rect(x + index * 120, y, *WAGER_CHIP_SIZE)
            self.chip_rects.append((rect, value))
            self.screen.blit(self.chip_images[("stacked", color)], rect)
            self._text(str(value), (rect.right + 8, rect.centery - 12), 24, "#f1d277")

    def _draw_selected_chips(self, start_x: int = 760, start_y: int = 505) -> None:
        self.selected_chip_rects = []
        chip_size = BET_CHIP_SIZE
        counts = Counter(self.selected_chips)
        for index, value in enumerate(CHIP_VALUES):
            if not counts[value]:
                continue
            color = CHIP_COLORS[CHIP_VALUES.index(value)]
            rect = pygame.Rect(start_x + index * 75, start_y, *chip_size)
            self.selected_chip_rects.append((rect, value))
            chip = pygame.transform.smoothscale(self.chip_images[("flat", color)], chip_size)
            self.screen.blit(chip, rect)
            if counts[value] > 1:
                self._text(f"x{counts[value]}", (rect.x - 2, rect.bottom + 2), 19, "#f1d277")

    def _draw_selected_chip(self) -> None:
        self._draw_selected_chips(start_x=820, start_y=455)

    def _draw_results(self):
        profile = self.profile or self.tracker.profile()
        self.screen.blit(self.title_font.render("DECISION RESULTS", True, "#f7e9b9"), (35, 25))
        self._text(f"DECISION SCORE: {profile.get('decision_score', 0)} / 100", (55, 100), 38, "#f1d277")
        lines = [
            f"Accuracy: {profile.get('accuracy', 0):.1%}",
            f"Average confidence: {profile.get('average_confidence', 0):.1%}",
            f"Calibration gap: {profile.get('calibration_gap', 0):+.1%}",
            f"Bet-weighted accuracy: {profile.get('bet_weighted_accuracy', 0):.1%}",
            f"HIT rate: {profile.get('player_hit_rate', 0):.1%} | Optimal HIT: {profile.get('optimal_hit_rate', 0):.1%}",
            f"EV lost to decisions: {profile.get('total_ev_regret', 0):.3f} units",
        ]
        for index, line in enumerate(lines):
            self._text(line, (65, 175 + index * 42), 25)
        projection = self.bankroll_projection or {}
        player = projection.get("player", {})
        optimal = projection.get("optimal", {})
        self._text(f"Player bankruptcy estimate: {player.get('bankruptcy_probability', 0):.1%}", (700, 175), 25)
        self._text(f"Optimal bankruptcy estimate: {optimal.get('bankruptcy_probability', 0):.1%}", (700, 220), 25)
        self._text("WHAT THE HOUSE LEARNED", (700, 330), 28, "#f1d277")
        for index, finding in enumerate(profile.get("findings", [])):
            self._text(f"• {finding}", (700, 375 + index * 35), 21)
        self._text("ENTER: play again | ESC: return to the room", (65, 665), 24, "#d8d0b8")
