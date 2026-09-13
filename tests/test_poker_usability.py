"""Poker usability and statistically fair feedback tests."""
from __future__ import annotations

from contextlib import redirect_stdout
from dataclasses import replace
import inspect
import io
import unittest

from game.poker_game import CONFIDENCE_TRACK, PokerGame, build_table_rows
from game.poker_models import (
    ActionOption,
    EquityResult,
    OpponentState,
    PokerAction,
    PokerActionEvaluation,
    PokerScenario,
    PreparedPokerRound,
)
from game.poker_tracker import PokerSessionTracker


def card(code: str) -> tuple[str, str]:
    suit = {"C": "clubs", "D": "diamonds", "H": "hearts", "S": "spades"}[code[-1]]
    return code[:-1], suit


def prepared_fixture() -> PreparedPokerRound:
    history = (
        PokerAction("SB", "post", 5),
        PokerAction("BB", "post", 10),
        PokerAction("UTG", "fold"),
        PokerAction("MP", "call", 10),
        PokerAction("CO", "raise", 30),
    )
    opponents = (
        OpponentState("UTG", 214, "TIGHT", 0, True, "FOLDED"),
        OpponentState("MP", 248, "BALANCED", 10, False, "CALLED 10"),
        OpponentState("CO", 110, "AGGRESSIVE", 30, False, "RAISED TO 30"),
        OpponentState("SB", 190, "LOOSE", 5, False, "POSTED 5"),
        OpponentState("BB", 211, "BALANCED", 10, False, "POSTED 10"),
    )
    scenario = PokerScenario(
        street="preflop",
        hero_cards=(card("AS"), card("QH")),
        board=(),
        hero_position="BTN",
        hero_stack=200,
        hero_contribution=0,
        starting_pot=30,
        pot=85,
        current_bet=30,
        last_full_raise=20,
        big_blind=10,
        opponents=opponents,
        action_history=history,
        archetype="usability test",
    )
    options = (
        ActionOption("fold", "fold", None, 0.0, 0.0),
        ActionOption("call", "call", 30, 30.2, 0.20),
        ActionOption("raise_90", "raise", 90, 30.7, 0.20),
        ActionOption("raise_120", "raise", 120, 20.0, 0.20),
    )
    evaluation = PokerActionEvaluation(
        options=options,
        best_key="raise_90",
        best_action="raise",
        best_amount=90,
        preferred_size_range=(90, 90),
        best_ev=30.7,
        decision_margin=0.5,
        difficulty="HARD",
        near_equivalent_keys=("call", "raise_90"),
    )
    equity = EquityResult(0.55, 0.50, 0.10, 0.40, 10_000, 0.005)
    return PreparedPokerRound(scenario, equity, evaluation)


def bare_game(prepared: PreparedPokerRound) -> PokerGame:
    game = PokerGame.__new__(PokerGame)
    game.prepared = prepared
    game.phase = "decision"
    game.round_number = 1
    game.confidence_percent = None
    game.selected_action = None
    game.selected_amount = None
    game.tracker = PokerSessionTracker()
    game.record = None
    return game


class PokerConfidenceAndLockTests(unittest.TestCase):
    def test_confidence_starts_unset_and_slider_maps_directly_to_zero_and_one_hundred(self) -> None:
        game = bare_game(prepared_fixture())
        self.assertIsNone(game.confidence_percent)
        game._set_confidence_from_mouse(CONFIDENCE_TRACK.left)
        self.assertEqual(game.confidence_percent, 0)
        game._set_confidence_from_mouse(CONFIDENCE_TRACK.right)
        self.assertEqual(game.confidence_percent, 100)
        game._set_confidence_from_mouse(CONFIDENCE_TRACK.left + round(CONFIDENCE_TRACK.width * 0.73))
        self.assertEqual(game.confidence_percent, 73)

    def test_action_cannot_lock_until_confidence_was_intentionally_selected(self) -> None:
        game = bare_game(prepared_fixture())
        with redirect_stdout(io.StringIO()):
            game._lock_decision("call", None)
        self.assertEqual(game.tracker.records, [])
        self.assertEqual(game.phase, "decision")

    def test_bet_or_raise_requires_a_valid_size_before_final_lock(self) -> None:
        game = bare_game(prepared_fixture())
        game.confidence_percent = 82
        game._select_action("raise")
        self.assertFalse(game._decision_ready())
        game.selected_amount = 89
        self.assertFalse(game._decision_ready())
        game.selected_amount = 90
        self.assertTrue(game._decision_ready())

    def test_selecting_a_complete_action_still_does_not_record_until_lock(self) -> None:
        game = bare_game(prepared_fixture())
        game.confidence_percent = 82
        game._select_action("call")
        self.assertTrue(game._decision_ready())
        self.assertEqual(game.tracker.records, [])
        with redirect_stdout(io.StringIO()):
            game._lock_selected_decision()
            game._lock_selected_decision()
        self.assertEqual(len(game.tracker.records), 1)

    def test_zero_percent_is_a_real_selected_confidence(self) -> None:
        game = bare_game(prepared_fixture())
        game.confidence_percent = 0
        game._select_action("call")
        self.assertTrue(game._decision_ready())
        with redirect_stdout(io.StringIO()):
            game._lock_selected_decision()
        self.assertIsNotNone(game.record)
        assert game.record is not None
        self.assertEqual(game.record.confidence_probability, 0.0)


class PokerTableAndHistoryTests(unittest.TestCase):
    def test_you_are_seated_in_position_order_and_pending_callers_remain_active(self) -> None:
        prepared = prepared_fixture()
        rows = build_table_rows(prepared.scenario)
        self.assertEqual([row.position for row in rows], ["UTG", "MP", "CO", "BTN", "SB", "BB"])
        you = next(row for row in rows if row.is_you)
        self.assertEqual((you.name, you.position, you.last_action), ("YOU", "BTN", "ACTION ON YOU"))
        mp = next(row for row in rows if row.position == "MP")
        self.assertEqual(mp.state, "ACTIVE")
        self.assertEqual(mp.amount_still_to_call, 20)
        self.assertIn("20 MORE TO CALL", mp.status_text)
        utg = next(row for row in rows if row.position == "UTG")
        self.assertEqual(utg.status_text, "FOLDED")

    def test_you_action_is_appended_chronologically_before_record_finalization(self) -> None:
        prepared = prepared_fixture()
        tracker = PokerSessionTracker()
        with redirect_stdout(io.StringIO()):
            record = tracker.lock_decision(prepared, 1, "call", None, 73)
        self.assertEqual(record.final_action_history[:-1], prepared.scenario.action_history)
        self.assertEqual(record.final_action_history[-1], PokerAction("YOU", "call", 30))
        self.assertEqual(record.as_dict()["action_history"][-1]["actor"], "YOU")

    def test_legal_actions_are_unchanged(self) -> None:
        self.assertEqual(prepared_fixture().scenario.legal_actions, ("fold", "call", "raise"))


class PokerFeedbackSemanticsTests(unittest.TestCase):
    def test_unstable_preference_cannot_be_labeled_a_clear_mistake(self) -> None:
        prepared = prepared_fixture()
        unstable = replace(
            prepared,
            evaluation=replace(
                prepared.evaluation,
                sensitivity_best_keys=("raise_90", "call"),
                model_sensitive=True,
            ),
        )
        tracker = PokerSessionTracker()
        with redirect_stdout(io.StringIO()):
            record = tracker.lock_decision(unstable, 1, "fold", None, 90)
        self.assertFalse(record.acceptable_action)
        self.assertEqual(record.decision_classification, "CLOSE / MODEL-SENSITIVE")

    def test_near_equivalent_is_reasonable_but_not_exactly_preferred(self) -> None:
        tracker = PokerSessionTracker()
        with redirect_stdout(io.StringIO()):
            record = tracker.lock_decision(prepared_fixture(), 1, "call", None, 73)
        self.assertFalse(record.exact_preferred)
        self.assertTrue(record.acceptable_action)
        self.assertTrue(record.action_correct)
        self.assertEqual(record.decision_classification, "CLOSE / MODEL-SENSITIVE")
        self.assertAlmostEqual(record.ev_regret, 0.5)

    def test_clearly_suboptimal_remains_incorrect(self) -> None:
        tracker = PokerSessionTracker()
        with redirect_stdout(io.StringIO()):
            record = tracker.lock_decision(prepared_fixture(), 1, "fold", None, 95)
        self.assertFalse(record.acceptable_action)
        self.assertEqual(record.decision_classification, "CLEAR MISTAKE")

    def test_action_family_and_sizing_quality_are_stored_separately(self) -> None:
        tracker = PokerSessionTracker()
        with redirect_stdout(io.StringIO()):
            record = tracker.lock_decision(prepared_fixture(), 1, "raise", 120, 80)
        self.assertTrue(record.action_family_preferred)
        self.assertFalse(record.sizing_acceptable)
        self.assertAlmostEqual(record.sizing_regret, 10.7)
        self.assertEqual(record.decision_classification, "CLEAR MISTAKE")

    def test_calibration_uses_reasonable_decisions_and_value_left_uses_raw_ev(self) -> None:
        tracker = PokerSessionTracker()
        with redirect_stdout(io.StringIO()):
            tracker.lock_decision(prepared_fixture(), 1, "call", None, 100)
            tracker.lock_decision(prepared_fixture(), 2, "fold", None, 100)
        summary = tracker.summary()
        self.assertEqual(summary["reasonable_decision_count"], 1)
        self.assertEqual(summary["exact_preferred_count"], 0)
        self.assertAlmostEqual(summary["action_accuracy"], 0.5)
        self.assertAlmostEqual(summary["calibration_gap"], 0.5)
        self.assertAlmostEqual(summary["value_left_on_table"], 31.2)
        self.assertAlmostEqual(
            summary["value_left_on_table"],
            summary["best_total_ev"] - summary["chosen_total_ev"],
        )

    def test_player_facing_summary_does_not_use_internal_regret_term(self) -> None:
        source = inspect.getsource(PokerGame._draw_summary).lower()
        self.assertNotIn("ev regret", source)
        self.assertNotIn("value left on the table", source)


if __name__ == "__main__":
    unittest.main()
