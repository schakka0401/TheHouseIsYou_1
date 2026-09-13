"""Regression tests for session-level Poker scenario randomization."""
from __future__ import annotations

import unittest

from game.poker_scenarios import ARCHETYPES, PokerScenarioGenerator


class PokerScenarioRandomnessTests(unittest.TestCase):
    def test_each_session_contains_all_archetypes_in_a_shuffled_order(self) -> None:
        generator = PokerScenarioGenerator(seed=17, equity_simulations=20)
        self.assertEqual(sorted(generator.archetype_order), sorted(ARCHETYPES))

    def test_different_unseeded_generators_do_not_use_one_fixed_archetype_order(self) -> None:
        orders = {tuple(PokerScenarioGenerator().archetype_order) for _ in range(8)}
        self.assertGreater(len(orders), 1)

    def test_seeded_generators_remain_reproducible(self) -> None:
        first = PokerScenarioGenerator(seed=91, equity_simulations=20)
        second = PokerScenarioGenerator(seed=91, equity_simulations=20)
        self.assertEqual(first.archetype_order, second.archetype_order)


if __name__ == "__main__":
    unittest.main()
