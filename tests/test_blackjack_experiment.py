"""Regression tests for the ten-round Blackjack decision experiment."""
from __future__ import annotations

from contextlib import redirect_stdout
import io
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from game.blackjack_engine import BlackjackEngine, Scenario, VERY_OBVIOUS_MARGIN, hand_value
from game.blackjack_game import (
    ACTION_PRESS_MS,
    BLACKJACK_ROUNDS,
    CONFIDENCE_CONFIRM,
    CONFIDENCE_TRACK,
    HIT_BUTTON,
    STAND_BUTTON,
    WAGER_CONFIRM,
    WAGER_FIELD,
    BlackjackGame,
)
from game.decision_tracker import CONFIDENCE_PROBABILITIES
from game.player_state import PlayerState


class ExactEvaluatorTests(unittest.TestCase):
    def test_exact_probabilities_and_visible_card_removal(self) -> None:
        engine = BlackjackEngine(seed=11)
        first = Scenario((("10", "hearts"), ("6", "clubs")), ("7", "spades"))
        second = Scenario((("9", "hearts"), ("7", "clubs")), ("7", "spades"))
        first_stats = engine.evaluate(first)
        second_stats = engine.evaluate(second)

        for action in ("hit", "stand"):
            stats = first_stats[action]
            self.assertAlmostEqual(
                stats.win_probability + stats.loss_probability + stats.push_probability,
                1.0,
                places=10,
            )
        # Both hands total 16, but their exact visible cards remove different
        # ranks from the finite deck and therefore produce different EVs.
        self.assertNotAlmostEqual(first_stats["hit"].ev, second_stats["hit"].ev, places=10)

    def test_scenario_mix_is_legal_and_nontrivial(self) -> None:
        engine = BlackjackEngine(seed=23)
        targets = ["EASY"] + ["MEDIUM"] * 6 + ["HARD"] * 3
        used = set()
        actual = []
        for target in targets:
            scenario, stats, difficulty = engine.generate_scenario(target, used)
            used.add(scenario.key)
            actual.append(difficulty)
            self.assertLess(hand_value(scenario.player_cards)[0], 21)
            self.assertGreaterEqual(len(scenario.player_cards), 2)
            self.assertEqual(len(set(scenario.player_cards + (scenario.dealer_upcard,))), len(scenario.player_cards) + 1)
            self.assertLess(abs(stats["hit"].ev - stats["stand"].ev), VERY_OBVIOUS_MARGIN)
        self.assertEqual(actual.count("EASY"), 1)
        self.assertEqual(actual.count("MEDIUM"), 6)
        self.assertEqual(actual.count("HARD"), 3)

    def test_total_twenty_one_is_not_a_measured_decision_state(self) -> None:
        engine = BlackjackEngine(seed=29)
        twenty_one = Scenario((("A", "hearts"), ("K", "clubs")), ("6", "spades"))
        with self.assertRaisesRegex(ValueError, "below 21"):
            engine.evaluate(twenty_one)


class BlackjackLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        pygame.init()
        cls.screen = pygame.display.set_mode((1280, 720))

    @classmethod
    def tearDownClass(cls) -> None:
        pygame.quit()

    def test_controls_and_exactly_one_decision_per_round(self) -> None:
        state = PlayerState(chips=200)
        output = io.StringIO()
        with redirect_stdout(output):
            game = BlackjackGame(self.screen, state, seed=31)

            self.assertEqual(game.round_number, 1)
            self.assertEqual(BLACKJACK_ROUNDS, 10)
            self.assertFalse(game.actions_enabled)
            for rect in (
                CONFIDENCE_TRACK,
                CONFIDENCE_CONFIRM,
                WAGER_FIELD,
                WAGER_CONFIRM,
                HIT_BUTTON,
                STAND_BUTTON,
            ):
                self.assertTrue(self.screen.get_rect().contains(rect))

            game._take_action("hit")
            self.assertEqual(len(game.tracker.records), 0)
            game._set_confidence(8)
            game._confirm_confidence()
            self.assertFalse(game.actions_enabled)
            game._set_wager_text("5")
            game._confirm_wager()
            self.assertTrue(game.actions_enabled)

            game._set_confidence(7)
            self.assertFalse(game.confidence_confirmed)
            self.assertFalse(game.actions_enabled)
            game._confirm_confidence()
            self.assertTrue(game.actions_enabled)
            game._set_wager_text("4")
            self.assertFalse(game.wager_confirmed)
            self.assertFalse(game.actions_enabled)
            game._confirm_wager()
            self.assertTrue(game.actions_enabled)

            before = state.chips
            game._take_action("hit")
            self.assertEqual(game.phase, "resolving")
            self.assertEqual(len(game.tracker.records), 1)
            game._take_action("stand")
            self.assertEqual(len(game.tracker.records), 1)
            game.action_pressed_at -= ACTION_PRESS_MS
            game.update()
            self.assertEqual(game.phase, "result")
            self.assertIn(state.chips - before, {-4, 0, 4})

            while len(game.tracker.records) < BLACKJACK_ROUNDS:
                game._queue_round()
                self.assertEqual(game.phase, "decision")
                game._set_confidence(5)
                game._confirm_confidence()
                game._set_wager_text("1")
                game._confirm_wager()
                game._take_action("hit" if game.round_number % 2 else "stand")
                game.action_pressed_at -= ACTION_PRESS_MS
                game.update()

            self.assertEqual(len(game.tracker.records), 10)
            self.assertEqual(game.round_number, 10)
            game._queue_round()
            self.assertEqual(game.phase, "analyzing")
            game.analysis_thread.join(timeout=30)
            self.assertFalse(game.analysis_thread.is_alive())
            game.update()

        self.assertEqual(game.phase, "results")
        self.assertEqual(game.profile["total_decisions"], 10)
        self.assertEqual(game.bankroll_projection["simulations"], 10_000)
        self.assertIn("ROUND 10 DEBUG", output.getvalue())
        self.assertIn("THE HOUSE SAYS", output.getvalue())
        self.assertIn("DETAILED DEBUG STATISTICS", output.getvalue())
        for record in game.tracker.records:
            self.assertIn(record.actual_round_result, {"win", "loss", "push"})
            self.assertIsNotNone(record.optimal_action)
            self.assertGreaterEqual(record.ev_regret, 0.0)

    def test_confidence_mapping(self) -> None:
        self.assertEqual(
            list(CONFIDENCE_PROBABILITIES.values()),
            [0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95, 0.99],
        )

    def test_chip_wagering_uses_clicks_and_requires_confirmation(self) -> None:
        state = PlayerState(chips=200)
        game = BlackjackGame(self.screen, state, seed=37)
        game._set_confidence(6)
        game._confirm_confidence()
        game.draw()

        chip_rect, chip_value = game.chip_rects[3]
        game.handle_event(pygame.event.Event(
            pygame.MOUSEBUTTONDOWN,
            {"button": 1, "pos": chip_rect.center},
        ))
        self.assertEqual(game.wager_text, str(chip_value))
        self.assertFalse(game.wager_confirmed)
        self.assertFalse(game.actions_enabled)

        game.handle_event(pygame.event.Event(
            pygame.MOUSEBUTTONDOWN,
            {"button": 1, "pos": WAGER_CONFIRM.center},
        ))
        self.assertTrue(game.wager_confirmed)
        self.assertTrue(game.actions_enabled)

        game.handle_event(pygame.event.Event(
            pygame.MOUSEBUTTONDOWN,
            {"button": 1, "pos": chip_rect.center},
        ))
        self.assertFalse(game.wager_confirmed)
        self.assertFalse(game.actions_enabled)

    def test_active_blackjack_owns_dealer_voice_and_queues_intro(self) -> None:
        calls: list[tuple] = []

        class VoiceSpy:
            def __init__(self, manager) -> None:
                calls.append(("init", manager))

            def clear_stale_dealer_lines(self, context, **options) -> None:
                calls.append(("context", context, options))

            def play_dealer_line(self, name, priority, *, context=None) -> str:
                calls.append(("play", name, priority, context))
                return "played"

            def update_dealer_voice(self) -> None:
                calls.append(("update",))

            def shutdown(self) -> None:
                calls.append(("shutdown",))

        shared_audio = object()
        with patch("game.blackjack_game.DealerVoiceManager", VoiceSpy):
            game = BlackjackGame(
                self.screen,
                PlayerState(chips=200),
                seed=47,
                menu_audio=SimpleNamespace(manager=shared_audio),
            )
            self.assertIn(("init", shared_audio), calls)
            self.assertTrue(any(call[:2] == ("play", "dealer_intro") for call in calls))
            game.update()
            self.assertIn(("update",), calls)
            action = game.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE))
            self.assertEqual(action, "room")
            self.assertIn(("shutdown",), calls)

    def test_results_paper_layout_and_rematch_controls(self) -> None:
        class AudioSpy:
            def __init__(self):
                self.switches = 0
                self.clicks = 0

            def switch(self):
                self.switches += 1

            def click(self):
                self.clicks += 1

        audio = AudioSpy()
        game = BlackjackGame(self.screen, PlayerState(chips=143), seed=43, menu_audio=audio)
        game.phase = "results"
        game.profile = {
            "decision_score": 78,
            "correct_decisions": 7,
            "total_decisions": 10,
            "average_confidence": 0.84,
            "accuracy": 0.70,
            "calibration_gap": 0.14,
            "starting_bankroll": 200,
            "actual_bankroll": 143,
            "expected_player_bankroll": 161.2,
            "expected_optimal_bankroll": 187.4,
            "findings": [
                "Your card decisions were strong: 7 of 10 were higher-EV.",
                "You put nearly your entire bankroll at risk on a single decision.",
                "Your final bankroll finished well above expectation; luck was on your side.",
            ],
        }
        game.bankroll_projection = {
            "horizon": 100,
            "risk_cap": 0.10,
            "player": {"bankruptcy_probability": 0.42},
            "optimal": {"bankruptcy_probability": 0.24},
            "risk_capped": {"bankruptcy_probability": 0.18},
        }
        game._invalidate_results_layout()
        game.draw()

        self.assertEqual(game.results_paper_source.get_size(), (447, 558))
        self.assertAlmostEqual(
            game.results_paper_rect.width / game.results_paper_rect.height,
            447 / 558,
            places=2,
        )
        for rect in game.result_element_rects:
            self.assertTrue(game.results_safe_rect.contains(rect))
        for previous, current in zip(game.result_element_rects, game.result_element_rects[1:]):
            self.assertLess(previous.bottom, current.top)

        for size in ((960, 540), (1600, 900)):
            game.screen = pygame.Surface(size)
            game._invalidate_results_layout()
            game.draw()
            self.assertEqual(game.results_paper_rect.center, game.screen.get_rect().center)
            for rect in game.result_element_rects:
                self.assertTrue(game.results_safe_rect.contains(rect))
            for previous, current in zip(game.result_element_rects, game.result_element_rects[1:]):
                self.assertLess(previous.bottom, current.top)

        outside = (game.results_paper_rect.left - 20, game.results_paper_rect.centery)
        game.handle_event(pygame.event.Event(pygame.MOUSEMOTION, pos=outside, buttons=(0, 0, 0)))
        game.handle_event(
            pygame.event.Event(
                pygame.MOUSEMOTION,
                pos=game.rematch_button.rect.center,
                buttons=(0, 0, 0),
            )
        )
        self.assertEqual(audio.switches, 1)
        game.handle_event(
            pygame.event.Event(
                pygame.MOUSEBUTTONDOWN,
                pos=game.rematch_button.rect.center,
                button=1,
            )
        )
        self.assertEqual(audio.clicks, 1)
        self.assertIsNotNone(game.pending_rematch_at)
        game.pending_rematch_at = 0
        game.update()
        self.assertEqual(game.phase, "decision")
        self.assertEqual(game.round_number, 1)
        self.assertEqual(len(game.tracker.records), 0)


if __name__ == "__main__":
    unittest.main()
