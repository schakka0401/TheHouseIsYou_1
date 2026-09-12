"""Sanity checks separating Blackjack decisions, wager risk, and luck."""
from __future__ import annotations

import copy
from contextlib import redirect_stdout
import io
import unittest

from game.bankroll_simulator import RISK_CAP, simulate_long_term_bankroll
from game.decision_tracker import DecisionRecord, DecisionTracker


def synthetic_lucky_all_in_records() -> list[DecisionRecord]:
    records: list[DecisionRecord] = []
    for index in range(1, 11):
        correct = index <= 9
        bet = 200 if index == 1 else 10
        bankroll_before = 200 if index == 1 else 400
        record = DecisionRecord(
            round_number=index,
            player_cards=["10 of hearts", "6 of clubs"],
            player_total=16,
            dealer_upcard="7 of spades",
            player_action="hit",
            confidence_level=7,
            confidence_probability=0.85,
            bet=bet,
            bankroll_before=bankroll_before,
            bankroll_after=550 if index == 10 else 400,
            actual_round_result="win" if index == 1 else "push",
        )
        record.optimal_action = "hit" if correct else "stand"
        record.decision_correct = correct
        record.ev_hit = 0.05 if correct else -0.07
        record.ev_stand = 0.00 if correct else 0.05
        record.ev_chosen = record.ev_hit
        record.ev_optimal = 0.05
        record.ev_regret = 0.0 if correct else 0.12
        record.decision_margin = abs(record.ev_hit - record.ev_stand)
        record.difficulty = "HARD" if record.decision_margin < 0.06 else "MEDIUM"
        if correct:
            record.win_probability_hit = 0.50
            record.loss_probability_hit = 0.45
            record.push_probability_hit = 0.05
            record.win_probability_stand = 0.475
            record.loss_probability_stand = 0.475
            record.push_probability_stand = 0.05
        else:
            record.win_probability_hit = 0.44
            record.loss_probability_hit = 0.51
            record.push_probability_hit = 0.05
            record.win_probability_stand = 0.50
            record.loss_probability_stand = 0.45
            record.push_probability_stand = 0.05
        records.append(record)
    return records


class ResultsMathTests(unittest.TestCase):
    def test_lucky_all_in_keeps_decision_risk_and_luck_separate(self) -> None:
        tracker = DecisionTracker()
        tracker.records = synthetic_lucky_all_in_records()
        profile = tracker.profile()

        expected_chosen = 200 + sum(record.bet * record.ev_chosen for record in tracker.records)
        expected_optimal = 200 + sum(record.bet * record.ev_optimal for record in tracker.records)
        self.assertEqual(profile["correct_decisions"], 9)
        self.assertEqual(profile["accuracy"], 0.90)
        self.assertEqual(profile["decision_score"], 86)
        self.assertLess(profile["average_ev_regret"], 0.02)
        self.assertEqual(profile["maximum_risk_fraction"], 1.0)
        self.assertEqual(profile["large_wager_count"], 1)
        self.assertEqual(profile["extreme_wager_count"], 1)
        self.assertEqual(profile["all_in_count"], 1)
        self.assertAlmostEqual(profile["expected_player_bankroll"], expected_chosen)
        self.assertAlmostEqual(profile["expected_optimal_bankroll"], expected_optimal)
        self.assertAlmostEqual(profile["luck_gap"], 550 - expected_chosen)
        self.assertGreater(profile["luck_gap"], 300)

        unlucky_records = copy.deepcopy(tracker.records)
        unlucky_records[-1].bankroll_after = 50
        unlucky_tracker = DecisionTracker()
        unlucky_tracker.records = unlucky_records
        self.assertEqual(unlucky_tracker.profile()["decision_score"], profile["decision_score"])

    def test_all_in_bootstrap_stays_high_risk_despite_optimal_decisions(self) -> None:
        tracker = DecisionTracker()
        tracker.records = synthetic_lucky_all_in_records()
        profile = tracker.profile()
        projection = simulate_long_term_bankroll(
            tracker.records,
            initial_bankroll=200,
            simulations=4_000,
            horizon=100,
            seed=913,
        )
        observed_risk = projection["player"]["bankruptcy_probability"]
        same_bet_optimal_risk = projection["optimal"]["bankruptcy_probability"]
        capped_risk = projection["risk_capped"]["bankruptcy_probability"]

        self.assertEqual(projection["risk_cap"], RISK_CAP)
        self.assertGreater(observed_risk, 0.85)
        self.assertGreater(same_bet_optimal_risk, 0.85)
        self.assertLess(abs(observed_risk - same_bet_optimal_risk), 0.10)
        self.assertLess(capped_risk, same_bet_optimal_risk - 0.50)

        findings = DecisionTracker.result_findings(profile, projection)
        self.assertTrue(any("higher-EV" in finding for finding in findings))
        risk_finding = next(finding for finding in findings if "all-in" in finding)
        self.assertIn("projected risk", risk_finding)
        self.assertIn("strong card decisions", risk_finding)
        self.assertTrue(any("luck" in finding.lower() for finding in findings))

    def test_console_report_explains_same_wagers_and_risk_analysis(self) -> None:
        tracker = DecisionTracker()
        tracker.records = synthetic_lucky_all_in_records()
        profile = tracker.profile()
        projection = simulate_long_term_bankroll(
            tracker.records,
            initial_bankroll=200,
            simulations=200,
            horizon=100,
            seed=27,
        )
        output = io.StringIO()
        with redirect_stdout(output):
            DecisionTracker.print_session_report(profile, projection)
        report = output.getvalue()
        self.assertIn("Expected with optimal HIT/STAND", report)
        self.assertIn("same wagers you placed", report)
        self.assertIn("RISK ANALYSIS", report)
        self.assertIn("Luck gap:", report)
        self.assertIn("Optimal decisions + 10% cap", report)


if __name__ == "__main__":
    unittest.main()
