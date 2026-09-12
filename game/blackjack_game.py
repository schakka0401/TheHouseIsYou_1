"""Interactive blackjack decision table."""
from __future__ import annotations

from pathlib import Path
import threading

import pygame

from game.bankroll_simulator import simulate_long_term_bankroll
from game.blackjack_engine import BlackjackEngine, Scenario, hand_value
from game.decision_tracker import DecisionRecord, DecisionTracker, confidence_probability
from game.player_state import PlayerState

BLACKJACK_SESSION_ROUNDS = 15
BANKROLL_SIMULATIONS = 10_000
BANKROLL_HORIZON = 100


class BlackjackGame:
    def __init__(self, screen: pygame.Surface, player_state: PlayerState, seed: int | None = None, simulations: int = 50_000):
        self.screen = screen
        self.player_state = player_state
        self.initial_bankroll = player_state.chips
        self.engine = BlackjackEngine(seed=seed, simulations=simulations)
        self.tracker = DecisionTracker()
        self.round_number = 0
        self.used_scenarios: set[tuple] = set()
        self.phase = "decision"
        self.action: str | None = None
        self.confidence_level: int | None = None
        self.wager_text = ""
        self.scenario: Scenario | None = None
        self.profile = None
        self.bankroll_projection = None
        self.analysis_thread: threading.Thread | None = None
        self.analysis_result = None
        self.analysis_error: Exception | None = None
        self.analysis_completed = 0
        self.analysis_total = 0
        self.card_images: dict[tuple[str, str], pygame.Surface] = {}
        self.title_font = pygame.font.Font(None, 42)
        self.font = pygame.font.Font(None, 27)
        self.small_font = pygame.font.Font(None, 22)
        self._load_card_images()
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

    def _queue_round(self) -> None:
        if self.round_number >= BLACKJACK_SESSION_ROUNDS or self.player_state.chips <= 0:
            self._finish_session()
            return
        self.scenario = self.engine.generate_raw_scenario(self.used_scenarios)
        self.used_scenarios.add(self.scenario.key)
        self.round_number += 1
        self.phase = "decision"
        self.action = None
        self.confidence_level = None
        self.wager_text = ""

    def update(self) -> None:
        if self.phase == "analyzing" and self.analysis_thread is not None and not self.analysis_thread.is_alive():
            if self.analysis_error:
                raise self.analysis_error
            self.profile, self.bankroll_projection = self.analysis_result
            self.phase = "results"

    def _finish_session(self) -> None:
        if self.phase == "analyzing" or self.phase == "results":
            return
        self.phase = "analyzing"
        self.analysis_completed = 0
        self.analysis_total = len(self.tracker.records)
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
                self.analysis_result = (profile, projection)
            except Exception as error:  # surfaced on the main thread in update()
                self.analysis_error = error

        self.analysis_thread = threading.Thread(target=analyze_session, daemon=True)
        self.analysis_thread.start()

    def _analysis_progress(self, completed: int, total: int) -> None:
        self.analysis_completed = completed
        self.analysis_total = total

    def _lock_round(self) -> None:
        if self.scenario is None or self.action is None or self.confidence_level is None:
            return
        bet = max(1, min(self.player_state.chips, int(self.wager_text or "0")))
        bankroll_before = self.player_state.chips
        result = self.engine.resolve(self.scenario, self.action)
        if result == "win":
            self.player_state.chips += bet
        elif result == "loss":
            self.player_state.chips -= bet
        player_total, _ = hand_value(list(self.scenario.player_cards))
        record = DecisionRecord(
            round_number=self.round_number,
            player_cards=[f"{rank} of {suit}" for rank, suit in self.scenario.player_cards],
            player_total=player_total,
            dealer_upcard=f"{self.scenario.dealer_upcard[0]} of {self.scenario.dealer_upcard[1]}",
            player_action=self.action,
            confidence_level=self.confidence_level,
            confidence_probability=confidence_probability(self.confidence_level),
            bet=bet,
            bankroll_before=bankroll_before,
            bankroll_after=self.player_state.chips,
            actual_round_result=result,
            scenario=self.scenario,
        )
        self.tracker.add(record)
        self.phase = "result"

    def handle_event(self, event: pygame.event.Event) -> str | None:
        if event.type != pygame.KEYDOWN:
            return None
        if event.key == pygame.K_ESCAPE:
            return "room"
        if self.phase in ("analyzing", "loading"):
            return None
        if self.phase == "decision":
            if event.key in (pygame.K_h, pygame.K_LEFT):
                self.action = "hit"
            elif event.key in (pygame.K_s, pygame.K_RIGHT):
                self.action = "stand"
            elif event.key in (pygame.K_RETURN, pygame.K_SPACE) and self.action:
                self.phase = "confidence"
        elif self.phase == "confidence":
            if pygame.K_1 <= event.key <= pygame.K_9:
                self.confidence_level = event.key - pygame.K_0
            elif event.key == pygame.K_0:
                self.confidence_level = 10
            elif event.key in (pygame.K_RETURN, pygame.K_SPACE) and self.confidence_level:
                self.phase = "wager"
        elif self.phase == "wager":
            if pygame.K_0 <= event.key <= pygame.K_9 and len(self.wager_text) < 6:
                self.wager_text += str(event.key - pygame.K_0)
            elif event.key == pygame.K_BACKSPACE:
                self.wager_text = self.wager_text[:-1]
            elif event.key == pygame.K_UP:
                self.wager_text = str(min(self.player_state.chips, max(1, int(self.wager_text or "0") + 1)))
            elif event.key == pygame.K_DOWN:
                self.wager_text = str(max(1, int(self.wager_text or "1") - 1))
            elif event.key in (pygame.K_RETURN, pygame.K_SPACE) and 1 <= int(self.wager_text or "0") <= self.player_state.chips:
                self._lock_round()
        elif self.phase == "result" and event.key in (pygame.K_RETURN, pygame.K_SPACE):
            if self.round_number >= BLACKJACK_SESSION_ROUNDS or self.player_state.chips <= 0:
                self._finish_session()
            else:
                self._queue_round()
        elif self.phase == "results" and event.key in (pygame.K_RETURN, pygame.K_SPACE):
            return "room"
        return None

    def _text(self, text, position, size=27, color=(245, 233, 190)):
        self.screen.blit(pygame.font.Font(None, size).render(text, True, color), position)

    def _draw_cards(self):
        for index, card in enumerate(self.scenario.player_cards):
            image = self.card_images.get(card)
            if image:
                self.screen.blit(image, (270 + index * 120, 150))
        dealer = self.card_images.get(self.scenario.dealer_upcard)
        if dealer:
            self.screen.blit(dealer, (850, 150))

    def draw(self):
        self.screen.fill("#154734")
        if self.phase == "analyzing":
            self.screen.blit(self.title_font.render("ANALYZING YOUR DECISIONS...", True, "#f7e9b9"), (35, 25))
            completed = self.analysis_completed
            total = max(1, self.analysis_total)
            percent = completed / total
            self._text("Running decision simulations...", (350, 330), 31, "#f1d277")
            self._text(f"Analyzing decision {completed} / {total}", (430, 385), 27)
            pygame.draw.rect(self.screen, "#3b2418", (310, 440, 660, 26), border_radius=10)
            pygame.draw.rect(self.screen, "#d29a32", (310, 440, int(660 * percent), 26), border_radius=10)
            self._text("The window remains responsive while the house studies the session.", (250, 520), 22)
            return
        if self.phase == "results":
            self._draw_results()
            return
        self.screen.blit(self.title_font.render("BLACKJACK DECISION TABLE", True, "#f7e9b9"), (35, 25))
        self._text(f"Round {self.round_number}/{BLACKJACK_SESSION_ROUNDS}", (950, 35))
        self._text(f"Shared bankroll: {self.player_state.chips} chips", (35, 80))
        self._draw_cards()
        player_total, _ = hand_value(list(self.scenario.player_cards))
        self._text(f"YOUR HAND: {player_total}", (270, 315), 31)
        self._text(f"DEALER UP: {self.scenario.dealer_upcard[0]}", (850, 315), 31)
        if self.phase == "decision":
            self._text("Choose an action: [H] HIT   [S] STAND, then press ENTER", (220, 420))
            self._text(f"Selected: {self.action.upper() if self.action else 'NONE'}", (480, 475), 34, "#f1d277")
        elif self.phase == "confidence":
            self._text("Before seeing the answer, choose confidence 1–10, then press ENTER", (170, 420))
            self._text(f"Confidence: {self.confidence_level or '_'} / 10", (480, 480), 35, "#f1d277")
        elif self.phase == "wager":
            self._text("Enter wager chips (1 to your bankroll), then press ENTER", (250, 420))
            self._text(f"Wager: {self.wager_text or '_'} chips", (480, 480), 35, "#f1d277")
        elif self.phase == "result":
            record = self.tracker.records[-1]
            self._text(f"Result: {record.actual_round_result.upper()}", (450, 415), 31)
            self._text("Decision recorded. Statistical analysis comes after the session.", (280, 465), 24)
            self._text("Press ENTER for the next scenario", (390, 550))
        self._text("ESC: return to room", (35, 680), 22, "#d8d0b8")

    def _draw_results(self):
        profile = self.profile or self.tracker.profile()
        self.screen.blit(self.title_font.render("DECISION RESULTS", True, "#f7e9b9"), (35, 25))
        self._text(f"DECISION SCORE: {profile.get('decision_score', 0)} / 100", (55, 100), 38, "#f1d277")
        lines = [
            f"Accuracy: {profile.get('accuracy', 0):.1%}",
            f"Average confidence: {profile.get('average_confidence', 0):.1%}",
            f"Calibration gap: {profile.get('calibration_gap', 0):+.1%}",
            f"Brier score: {profile.get('brier_score', 0):.3f}",
            f"Bet-weighted accuracy: {profile.get('bet_weighted_accuracy', 0):.1%}",
            f"HIT rate: {profile.get('player_hit_rate', 0):.1%}  |  Optimal HIT rate: {profile.get('optimal_hit_rate', 0):.1%}",
            f"EV lost to decisions: {profile.get('total_ev_regret', 0):.3f} units",
        ]
        for index, line in enumerate(lines):
            self._text(line, (65, 175 + index * 42), 27)
        components = profile.get("score_components", {})
        self._text(
            "Score components: "
            f"quality {components.get('decision_quality', 0)}  "
            f"calibration {components.get('confidence_calibration', 0)}  "
            f"bet discipline {components.get('bet_discipline', 0)}  "
            f"EV efficiency {components.get('ev_efficiency', 0)}",
            (65, 485), 20, "#f1d277",
        )
        projection = self.bankroll_projection or {}
        player = projection.get("player", {})
        optimal = projection.get("optimal", {})
        self._text(f"Player bankruptcy estimate: {player.get('bankruptcy_probability', 0):.1%}", (700, 175), 27)
        self._text(f"Player median ending bankroll: {player.get('median_ending_bankroll', 0):.0f}", (700, 220), 27)
        self._text(f"Optimal bankruptcy estimate: {optimal.get('bankruptcy_probability', 0):.1%}", (700, 265), 27)
        self._text(f"Optimal median ending bankroll: {optimal.get('median_ending_bankroll', 0):.0f}", (700, 310), 27)
        self._text("FINDINGS", (700, 390), 30, "#f1d277")
        for index, finding in enumerate(profile.get("findings", [])):
            self._text(f"• {finding}", (700, 435 + index * 35), 22)
        self._text("ENTER: return to the room", (65, 665), 24, "#d8d0b8")
