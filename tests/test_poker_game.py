"""Lifecycle integration tests for the active Poker minigame."""
from __future__ import annotations

from contextlib import redirect_stdout
import io
import os
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from game.player_state import PlayerState
from game.poker_game import PokerGame
from game.poker_scenarios import POKER_ROUNDS


class PokerGameLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        pygame.init()
        cls.screen = pygame.display.set_mode((1280, 720))

    @classmethod
    def tearDownClass(cls) -> None:
        pygame.quit()

    def test_five_rounds_record_exactly_five_decisions_without_mutating_bankroll(self) -> None:
        state = PlayerState(chips=200)
        output = io.StringIO()
        with redirect_stdout(output):
            game = PokerGame(self.screen, state, seed=4, equity_simulations=150)
            for expected_round in range(1, POKER_ROUNDS + 1):
                game.loading_thread.join(timeout=5)
                self.assertFalse(game.loading_thread.is_alive())
                game.update()
                self.assertEqual(game.phase, "decision")
                self.assertEqual(game.round_number, expected_round)
                self.assertIsNone(game.confidence_percent)
                game.draw()
                self.assertGreaterEqual(len(game.action_buttons), 2)

                game.confidence_percent = 70
                best = game.prepared.evaluation
                game._select_action(best.best_action)
                if best.best_action in {"bet", "raise"}:
                    game.selected_amount = best.best_amount
                self.assertTrue(game._decision_ready())
                game._lock_selected_decision()
                game._lock_selected_decision()
                self.assertEqual(len(game.tracker.records), expected_round)
                self.assertEqual(game.phase, "result")
                game._start_round_loading()

        self.assertEqual(game.phase, "summary")
        game.draw()
        self.assertEqual(len(game.tracker.records), POKER_ROUNDS)
        self.assertEqual(state.chips, 200)
        self.assertIn("POKER ROUND 5 / 5", output.getvalue())
        self.assertIn("POKER SESSION SUMMARY", output.getvalue())


if __name__ == "__main__":
    unittest.main()
