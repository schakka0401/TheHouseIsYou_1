"""Targeted mathematical audit tests for player-facing Poker advice."""
from __future__ import annotations

from dataclasses import replace
import unittest

from game.poker_audit import (
    benchmark_scenarios,
    card,
    exact_single_opponent_equity,
    reference_five,
    reference_equity,
)
from game.poker_equity import PokerEquityEstimator
from game.poker_ev import PokerEVModel, REALIZATION_BY_STREET
from game.poker_hand_evaluator import evaluate_five
from game.poker_models import ActionOption, EquityResult
from game.poker_ranges import PokerRangeModel


class PokerBenchmarkAuditTests(unittest.TestCase):
    def test_twelve_benchmarks_have_requested_distribution(self) -> None:
        benchmarks = benchmark_scenarios()
        self.assertEqual(len(benchmarks), 12)
        self.assertEqual(sum(item.name.startswith("P") for item in benchmarks), 2)
        self.assertEqual(sum(item.name.startswith("F") for item in benchmarks), 3)
        self.assertEqual(sum(item.name.startswith("T") for item in benchmarks), 3)
        self.assertEqual(sum(item.name.startswith("R") for item in benchmarks), 3)
        self.assertEqual(sum(item.name.startswith("M") for item in benchmarks), 1)

    def test_independent_reference_hand_ranker_matches_known_categories(self) -> None:
        hands = (
            tuple(card(code) for code in ("AS", "KS", "QS", "JS", "10S")),
            tuple(card(code) for code in ("AH", "AD", "AC", "AS", "2D")),
            tuple(card(code) for code in ("AS", "2D", "3C", "4H", "5S")),
            tuple(card(code) for code in ("AH", "JD", "8C", "5S", "2D")),
        )
        for hand in hands:
            self.assertEqual(reference_five(hand), evaluate_five(hand))

    def test_river_equity_matches_independent_exhaustive_reference(self) -> None:
        for index, benchmark in enumerate(benchmark_scenarios()[8:11]):
            ranges = PokerRangeModel()
            production = PokerEquityEstimator(ranges, simulations=5_000, seed=20 + index).estimate(
                benchmark.scenario
            )
            reference = reference_equity(benchmark.scenario, ranges)
            self.assertEqual(reference.method, "exhaustive")
            self.assertLess(abs(production.equity - reference.equity), 0.035)

    def test_known_cards_never_collide_and_folded_opponents_are_excluded(self) -> None:
        scenario = benchmark_scenarios()[8].scenario
        estimator = PokerEquityEstimator(PokerRangeModel(), simulations=100, seed=17)
        table_known = set(scenario.hero_cards + scenario.board)
        for _ in range(25):
            sampled = estimator.sample_opponent_hands(scenario)
            self.assertEqual(set(sampled), {opponent.position for opponent in scenario.active_opponents})
            blocked = set(table_known)
            for hand in sampled.values():
                self.assertFalse(blocked.intersection(hand))
                blocked.update(hand)

        changed_folded = tuple(
            replace(opponent, profile="AGGRESSIVE") if opponent.folded else opponent
            for opponent in scenario.opponents
        )
        altered = replace(scenario, opponents=changed_folded)
        original_equity = PokerEquityEstimator(PokerRangeModel(), 2_000, 55).estimate(scenario)
        altered_equity = PokerEquityEstimator(PokerRangeModel(), 2_000, 55).estimate(altered)
        self.assertEqual(original_equity, altered_equity)

    def test_fold_check_and_call_formulas_use_incremental_cost(self) -> None:
        check_scenario = benchmark_scenarios()[2].scenario
        equity = EquityResult(0.40, 0.38, 0.04, 0.58, 10_000, 0.005)
        model = PokerEVModel(branch_simulations=20, seed=1)
        self.assertAlmostEqual(model._check_ev(check_scenario, equity), 0.40 * 100 * 0.79)

        call_scenario = benchmark_scenarios()[5].scenario
        expected = 0.40 * (125 + 25) * REALIZATION_BY_STREET["turn"] - 25
        self.assertAlmostEqual(model._call_ev(call_scenario, equity), expected)
        evaluation = model.evaluate(call_scenario, equity)
        self.assertEqual(evaluation.option_for("fold").ev, 0.0)

    def test_calling_ranges_strengthen_with_pressure(self) -> None:
        scenario = benchmark_scenarios()[4].scenario
        opponent = scenario.active_opponents[0]
        ranges = PokerRangeModel()
        model = PokerEVModel(ranges, branch_simulations=20, seed=2)
        small = ranges.conditional_calling_range(scenario, opponent, 45)
        large = ranges.conditional_calling_range(scenario, opponent, 300)
        self.assertGreater(large.fold_probability, small.fold_probability)
        self.assertGreater(large.calling_mean_strength, small.calling_mean_strength)

    def test_river_raise_conditions_a_stronger_range_than_river_bet(self) -> None:
        scenario = benchmark_scenarios()[8].scenario
        bettor = scenario.active_opponents[0]
        raiser = replace(bettor, status="RAISED TO 140")
        ranges = PokerRangeModel()
        bet_range = ranges.conditional_calling_range(scenario, bettor, 100)
        raised_scenario = replace(scenario, opponents=(raiser,) + scenario.opponents[1:])
        raise_range = ranges.conditional_calling_range(raised_scenario, raiser, 100)
        self.assertGreater(raise_range.prior_mean_strength, bet_range.prior_mean_strength)

    def test_adding_active_opponents_reduces_showdown_equity(self) -> None:
        scenario = benchmark_scenarios()[2].scenario
        additional = tuple(
            replace(opponent, folded=False, status="CHECKED") if opponent.position == "BB" else opponent
            for opponent in scenario.opponents
        )
        multiway = replace(scenario, opponents=additional)
        heads_up_equity = PokerEquityEstimator(PokerRangeModel(), 4_000, 70).estimate(scenario)
        multiway_equity = PokerEquityEstimator(PokerRangeModel(), 4_000, 70).estimate(multiway)
        self.assertLess(multiway_equity.equity, heads_up_equity.equity)

    def test_tighter_river_calling_range_reduces_hero_called_equity(self) -> None:
        scenario = benchmark_scenarios()[8].scenario
        equities = []
        for profile in ("LOOSE", "BALANCED", "TIGHT"):
            opponent = replace(scenario.active_opponents[0], profile=profile)
            profiled = replace(scenario, opponents=(opponent,) + scenario.opponents[1:])
            ranges = PokerRangeModel()
            model = PokerEVModel(ranges, branch_simulations=20, seed=3)
            calling = ranges.conditional_calling_range(profiled, opponent, 175)
            equities.append(exact_single_opponent_equity(profiled, calling.weighted_combos).equity)
        self.assertGreater(equities[0], equities[1])
        self.assertGreater(equities[1], equities[2])

    def test_aggressive_trace_accounts_for_every_branch(self) -> None:
        scenario = benchmark_scenarios()[4].scenario
        ranges = PokerRangeModel()
        equity = PokerEquityEstimator(ranges, 500, 8).estimate(scenario)
        evaluation = PokerEVModel(ranges, branch_simulations=200, seed=9).evaluate(scenario, equity)
        option = evaluation.option_for("bet", scenario.candidate_bet_sizes[0])
        trace = option.aggressive_trace
        self.assertIsNotNone(trace)
        assert trace is not None
        self.assertAlmostEqual(sum(branch.probability for branch in trace.branches), 1.0)
        self.assertAlmostEqual(sum(branch.weighted_ev for branch in trace.branches), option.ev)
        for response in trace.opponent_responses:
            self.assertGreater(response.calling_mean_strength, response.prior_mean_strength)

    def test_near_equal_tolerance_uses_practical_and_statistical_uncertainty(self) -> None:
        best = ActionOption("raise_to_180", "raise", 180, 22.1, 1.2)
        close = ActionOption("call", "call", 60, 21.9, 1.0)
        clearly_worse = ActionOption("fold", "fold", None, 0.0)
        self.assertTrue(PokerEVModel._near_equal(best, close, 120))
        self.assertFalse(PokerEVModel._near_equal(best, clearly_worse, 120))

    def test_baseline_fold_probability_is_monotonic_but_saturating(self) -> None:
        scenario = benchmark_scenarios()[4].scenario
        opponent = scenario.active_opponents[0]
        model = PokerEVModel(branch_simulations=20, seed=4)
        probabilities = [model.fold_probability(opponent, scenario, cost) for cost in (25, 50, 100, 300)]
        self.assertEqual(probabilities, sorted(probabilities))
        self.assertLess(probabilities[-1] - probabilities[-2], probabilities[2] - probabilities[0])


if __name__ == "__main__":
    unittest.main()
