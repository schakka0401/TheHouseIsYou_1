"""Auditable tests for the first-pass Hold'em decision engine."""
from __future__ import annotations

import unittest

from game.poker_betting import PokerActionHistory
from game.poker_equity import PokerEquityEstimator
from game.poker_ev import PokerEVModel
from game.poker_hand_evaluator import evaluate_five, evaluate_holdem, showdown_share
from game.poker_models import EquityResult, OpponentState, PokerScenario
from game.poker_ranges import PokerRangeModel
from game.poker_scenarios import PokerScenarioGenerator


def card(code: str) -> tuple[str, str]:
    suit = {"C": "clubs", "D": "diamonds", "H": "hearts", "S": "spades"}[code[-1]]
    return code[:-1], suit


def scenario_fixture(
    *,
    hero_cards=(card("AH"), card("KD")),
    board=(card("2C"), card("7D"), card("9S"), card("JH"), card("3C")),
    pot=120,
    current_bet=0,
    hero_stack=200,
    hero_contribution=0,
    last_full_raise=10,
) -> PokerScenario:
    opponents = (
        OpponentState("SB", 180, "TIGHT", current_bet, False, "CHECKED" if not current_bet else f"BET {current_bet}"),
        OpponentState("BB", 220, "BALANCED", 0, False, "WAITING"),
        OpponentState("CO", 160, "LOOSE", 0, True, "FOLDED"),
    )
    return PokerScenario(
        street="river",
        hero_cards=hero_cards,
        board=board,
        hero_position="BTN",
        hero_stack=hero_stack,
        hero_contribution=hero_contribution,
        starting_pot=pot - current_bet,
        pot=pot,
        current_bet=current_bet,
        last_full_raise=last_full_raise,
        big_blind=10,
        opponents=opponents,
        action_history=(),
        archetype="test",
    )


class HoldemHandEvaluatorTests(unittest.TestCase):
    def test_all_hand_categories_rank_in_correct_order(self) -> None:
        hands = (
            (card("AS"), card("KS"), card("QS"), card("JS"), card("10S")),
            (card("AH"), card("AD"), card("AC"), card("AS"), card("2D")),
            (card("KH"), card("KD"), card("KC"), card("2S"), card("2D")),
            (card("AH"), card("JH"), card("8H"), card("4H"), card("2H")),
            (card("9H"), card("8D"), card("7C"), card("6S"), card("5H")),
            (card("QH"), card("QD"), card("QC"), card("7S"), card("2D")),
            (card("JH"), card("JD"), card("4C"), card("4S"), card("2D")),
            (card("10H"), card("10D"), card("8C"), card("5S"), card("2D")),
            (card("AH"), card("JD"), card("8C"), card("5S"), card("2D")),
        )
        self.assertEqual([evaluate_five(hand)[0] for hand in hands], list(range(8, -1, -1)))

    def test_wheel_straight_uses_five_as_high_card(self) -> None:
        score = evaluate_five((card("AS"), card("2D"), card("3C"), card("4H"), card("5S")))
        self.assertEqual(score, (4, 5))

    def test_holdem_chooses_best_five_and_ties_split(self) -> None:
        board = (card("10S"), card("JS"), card("QS"), card("KS"), card("AS"))
        hero = evaluate_holdem((card("2C"), card("3D")), board)
        villain = evaluate_holdem((card("9H"), card("9D")), board)
        self.assertEqual(hero, villain)
        self.assertEqual(showdown_share(hero, [villain]), 0.5)


class BettingLegalityTests(unittest.TestCase):
    def test_cannot_check_while_facing_a_bet(self) -> None:
        history = PokerActionHistory(("SB", "BTN"), {"SB": 200, "BTN": 200}, 0)
        history.post("BTN", 10)
        with self.assertRaisesRegex(ValueError, "Cannot check"):
            history.act("SB", "check")

    def test_out_of_order_and_undersized_raises_are_rejected(self) -> None:
        history = PokerActionHistory(("SB", "BTN"), {"SB": 200, "BTN": 200}, 0)
        with self.assertRaisesRegex(ValueError, "out of order"):
            history.act("BTN", "check")
        history.act("SB", "bet", 20)
        with self.assertRaisesRegex(ValueError, "below legal minimum"):
            history.act("BTN", "raise", 30)

    def test_call_amount_minimum_raise_and_legal_actions(self) -> None:
        scenario = scenario_fixture(current_bet=65, pot=185, last_full_raise=65)
        self.assertEqual(scenario.amount_to_call, 65)
        self.assertEqual(scenario.minimum_raise_to, 130)
        self.assertEqual(scenario.legal_actions, ("fold", "call", "raise"))
        self.assertNotIn("check", scenario.legal_actions)

    def test_unopened_pot_exposes_check_and_bet(self) -> None:
        scenario = scenario_fixture()
        self.assertEqual(scenario.legal_actions, ("check", "bet"))
        self.assertTrue(scenario.candidate_bet_sizes)

    def test_raise_sizes_obey_minimum_and_stack_all_in_bound(self) -> None:
        scenario = scenario_fixture(current_bet=65, pot=185, hero_stack=175, last_full_raise=35)
        self.assertTrue(all(amount >= scenario.minimum_raise_to for amount in scenario.candidate_raise_sizes))
        self.assertTrue(all(amount <= scenario.hero_stack for amount in scenario.candidate_raise_sizes))
        self.assertIn(scenario.hero_stack, scenario.candidate_raise_sizes)

    def test_candidate_sizes_are_capped_by_effective_stack(self) -> None:
        scenario = scenario_fixture(hero_stack=400)
        self.assertEqual(scenario.effective_stack, 220)
        self.assertTrue(all(amount <= scenario.effective_stack for amount in scenario.candidate_bet_sizes))
        self.assertIn(scenario.effective_stack, scenario.candidate_bet_sizes)

    def test_short_all_in_is_only_legal_raise_size(self) -> None:
        scenario = scenario_fixture(current_bet=65, pot=185, hero_stack=80, last_full_raise=35)
        self.assertEqual(scenario.candidate_raise_sizes, (80,))

    def test_impossible_scenarios_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicate"):
            scenario_fixture(hero_cards=(card("AH"), card("AH")))
        with self.assertRaisesRegex(ValueError, "requires 5"):
            scenario_fixture(board=(card("2C"), card("7D"), card("9S"), card("JH")))


class RangeEquityAndEVTests(unittest.TestCase):
    def test_action_conditioning_narrows_ranges_in_expected_direction(self) -> None:
        model = PokerRangeModel()
        premium = (card("AS"), card("AH"))
        weak = (card("7C"), card("2D"))
        self.assertGreater(
            model.preflop_weight(premium, "TIGHT", "CO", "RAISED TO 30"),
            model.preflop_weight(weak, "TIGHT", "CO", "RAISED TO 30"),
        )

    def test_sampled_opponent_ranges_never_collide(self) -> None:
        scenario = PokerScenarioGenerator(seed=3, equity_simulations=20)._build_preflop(200)
        model = PokerRangeModel()
        blocked = set(scenario.hero_cards + scenario.board)
        import random
        rng = random.Random(9)
        for opponent in scenario.active_opponents:
            combo = model.sample_combo(scenario, opponent, blocked, rng)
            self.assertTrue(blocked.isdisjoint(combo))
            blocked.update(combo)

    def test_complete_board_tie_splits_multiway_pot(self) -> None:
        board = (card("10S"), card("JS"), card("QS"), card("KS"), card("AS"))
        scenario = scenario_fixture(hero_cards=(card("2C"), card("3D")), board=board)
        result = PokerEquityEstimator(simulations=120, seed=5).estimate(scenario)
        self.assertAlmostEqual(result.tie_probability, 1.0)
        self.assertAlmostEqual(result.equity, 1 / 3)

    def test_unbeatable_quads_have_full_equity(self) -> None:
        scenario = scenario_fixture(
            hero_cards=(card("AC"), card("AD")),
            board=(card("AS"), card("AH"), card("KC"), card("QD"), card("2S")),
        )
        result = PokerEquityEstimator(simulations=120, seed=7).estimate(scenario)
        self.assertEqual(result.win_probability, 1.0)
        self.assertEqual(result.equity, 1.0)

    def test_fold_ev_is_zero(self) -> None:
        scenario = scenario_fixture(current_bet=50, pot=170, last_full_raise=50)
        equity = EquityResult(0.45, 0.42, 0.06, 0.52, 100)
        evaluation = PokerEVModel().evaluate(scenario, equity)
        self.assertEqual(evaluation.action_evs["fold"], 0.0)

    def test_larger_pressure_increases_fold_probability(self) -> None:
        scenario = scenario_fixture(current_bet=50, pot=170, last_full_raise=50)
        opponent = scenario.active_opponents[0]
        model = PokerEVModel()
        self.assertGreater(
            model.fold_probability(opponent, scenario, 170),
            model.fold_probability(opponent, scenario, 50),
        )

    def test_generated_session_has_legal_unique_diverse_scenarios(self) -> None:
        generator = PokerScenarioGenerator(seed=4, equity_simulations=250)
        rounds = [generator.generate_round(index, 200) for index in range(1, 6)]
        self.assertEqual([item.scenario.street for item in rounds], ["preflop", "flop", "turn", "turn", "river"])
        for item in rounds:
            scenario = item.scenario
            known = scenario.hero_cards + scenario.board
            self.assertEqual(len(known), len(set(known)))
            self.assertGreaterEqual(len(scenario.legal_actions), 2)
            self.assertLess(item.evaluation.decision_margin / scenario.pot, 0.45)


if __name__ == "__main__":
    unittest.main()
