"""Poker decision records, audit output, and cautious five-round summary."""
from __future__ import annotations

from statistics import mean

from game.poker_ev import PokerEVModel
from game.poker_models import PokerAction, PokerDecisionRecord, PreparedPokerRound, card_code


class PokerSessionTracker:
    def __init__(self) -> None:
        self.records: list[PokerDecisionRecord] = []

    def lock_decision(
        self,
        prepared: PreparedPokerRound,
        round_number: int,
        action: str,
        amount: int | None,
        confidence_percent: int,
    ) -> PokerDecisionRecord:
        if not 0 <= confidence_percent <= 100:
            raise ValueError("Poker confidence must be between 0 and 100 percent")
        option = prepared.evaluation.option_for(action, amount)
        chosen_ev = option.ev
        best_ev = prepared.evaluation.best_ev
        exact_preferred = option.key == prepared.evaluation.best_key
        sensitivity_winners = set(prepared.evaluation.sensitivity_best_keys)
        acceptable_action = (
            option.key in prepared.evaluation.near_equivalent_keys
            or option.key in sensitivity_winners
        )
        action_family_preferred = action == prepared.evaluation.best_action
        same_action = [candidate for candidate in prepared.evaluation.options if candidate.action == action]
        same_action_best = max(same_action, key=lambda candidate: candidate.ev)
        sizing_regret = (
            max(0.0, same_action_best.ev - chosen_ev)
            if action in {"bet", "raise"} and same_action else 0.0
        )
        sizing_acceptable = (
            PokerEVModel._near_equal(same_action_best, option, prepared.scenario.pot)
            if action in {"bet", "raise"} and same_action else True
        )
        competing_near_equal = any(
            key != prepared.evaluation.best_key
            for key in prepared.evaluation.near_equivalent_keys
        )
        if acceptable_action and (prepared.evaluation.model_sensitive or competing_near_equal):
            classification = "CLOSE / MODEL-SENSITIVE"
        elif acceptable_action:
            classification = "REASONABLE"
        else:
            classification = "CLEAR MISTAKE"
        final_action = PokerAction("YOU", action, option.amount or 0)
        record = PokerDecisionRecord(
            round_number=round_number,
            scenario=prepared.scenario,
            equity=prepared.equity,
            evaluation=prepared.evaluation,
            final_action_history=prepared.scenario.action_history + (final_action,),
            player_action=action,
            player_amount=option.amount,
            confidence_percent=confidence_percent,
            confidence_probability=confidence_percent / 100.0,
            chosen_ev=chosen_ev,
            best_ev=best_ev,
            ev_regret=max(0.0, best_ev - chosen_ev),
            exact_preferred=exact_preferred,
            acceptable_action=acceptable_action,
            action_family_preferred=action_family_preferred,
            sizing_acceptable=sizing_acceptable,
            decision_classification=classification,
            action_correct=acceptable_action,
            sizing_regret=sizing_regret,
        )
        self.records.append(record)
        self.print_round_debug(record)
        return record

    def summary(self) -> dict:
        if not self.records:
            return {}
        count = len(self.records)
        exact_preferred = sum(record.exact_preferred for record in self.records)
        reasonable = sum(record.acceptable_action for record in self.records)
        close_decisions = sum(record.decision_classification == "CLOSE / MODEL-SENSITIVE" for record in self.records)
        clear_mistakes = sum(record.decision_classification == "CLEAR MISTAKE" for record in self.records)
        preferred_families = sum(record.action_family_preferred for record in self.records)
        accuracy = reasonable / count
        average_confidence = mean(record.confidence_probability for record in self.records)
        calibration_gap = average_confidence - accuracy
        brier = mean(
            (record.confidence_probability - float(record.acceptable_action)) ** 2
            for record in self.records
        )
        total_regret = sum(record.ev_regret for record in self.records)
        chosen_total_ev = sum(record.chosen_ev for record in self.records)
        best_total_ev = sum(record.best_ev for record in self.records)
        value_left_on_table = max(0.0, best_total_ev - chosen_total_ev)
        aggressive = sum(record.player_action in {"bet", "raise"} for record in self.records) / count
        preferred_aggressive = sum(
            record.evaluation.best_action in {"bet", "raise"} for record in self.records
        ) / count
        sized = [record.sizing_regret for record in self.records if record.player_action in {"bet", "raise"}]
        action_frequencies = {
            action: sum(record.player_action == action for record in self.records) / count
            for action in ("fold", "call", "check", "bet", "raise")
        }
        observations: list[str] = []
        if calibration_gap >= 0.12:
            observations.append("In these five decisions, your confidence ran ahead of your decision accuracy.")
        elif calibration_gap <= -0.12:
            observations.append("In these five decisions, your choices matched the model more often than your confidence suggested.")

        poor_sizes = [
            record for record in self.records
            if record.player_action in {"bet", "raise"} and not record.sizing_acceptable
        ]
        if poor_sizes:
            too_large = sum(
                record.player_amount is not None
                and record.evaluation.best_amount is not None
                and record.player_amount > record.evaluation.best_amount
                for record in poor_sizes
            )
            wording = (
                "Your bet and raise sizes tended to risk more than the model preferred."
                if too_large > len(poor_sizes) / 2
                else "Your stronger decisions often used sizes that left value on the table."
            )
            observations.append(wording)
        elif sized:
            observations.append("Your bet and raise sizes were generally within the model's preferred range.")
        elif aggressive - preferred_aggressive >= 0.20:
            observations.append("You applied pressure more often than the model considered worthwhile.")
        elif preferred_aggressive - aggressive >= 0.20:
            observations.append("You passed on aggressive actions more often than the model preferred.")
        elif value_left_on_table <= max(5.0, sum(record.scenario.pot for record in self.records) * 0.03):
            observations.append("Your decisions were generally reasonable, with only small differences from the model's preferred lines.")

        if not observations and reasonable >= count * 0.6:
            observations.append("Your decisions were generally reasonable, with only small differences from the model's preferred lines.")

        high_confidence_clear = [
            record for record in self.records
            if record.confidence_percent >= 80 and record.decision_classification == "CLEAR MISTAKE"
        ]
        if len(high_confidence_clear) >= 2:
            confidence_insight = "Your confidence stayed high even when several decisions lost meaningful value."
        elif len(high_confidence_clear) == 1:
            confidence_insight = "You were highly confident on one decision where the model strongly preferred another action."
        elif accuracy >= 0.8 and average_confidence <= 0.55:
            confidence_insight = "Your decisions were stronger than your confidence suggested."
        elif accuracy >= 0.8 and average_confidence <= 0.65:
            confidence_insight = "You seemed to recognize when you were uncertain."
        else:
            confidence_insight = None

        return {
            "rounds": count,
            # Player-facing count includes statistically/practically near-equivalent choices.
            "preferred_action_count": reasonable,
            "reasonable_decision_count": reasonable,
            "close_decision_count": close_decisions,
            "clear_mistake_count": clear_mistakes,
            "exact_preferred_count": exact_preferred,
            "preferred_action_family_count": preferred_families,
            "action_family_accuracy": preferred_families / count,
            "action_accuracy": accuracy,
            "average_confidence": average_confidence,
            "calibration_gap": calibration_gap,
            "brier_score": brier,
            "total_ev_regret": total_regret,
            "average_ev_regret": total_regret / count,
            "chosen_total_ev": chosen_total_ev,
            "best_total_ev": best_total_ev,
            "value_left_on_table": value_left_on_table,
            "player_aggression_frequency": aggressive,
            "model_aggression_frequency": preferred_aggressive,
            "average_sizing_regret": mean(sized) if sized else 0.0,
            "action_frequencies": action_frequencies,
            "observations": observations[:2],
            "confidence_insight": confidence_insight,
        }

    @staticmethod
    def print_round_debug(record: PokerDecisionRecord) -> None:
        scenario = record.scenario
        evaluation = record.evaluation
        print("\n" + "=" * 50)
        print(f"POKER ROUND {record.round_number} / 5")
        print("=" * 50)
        print(f"\nStreet:\n{scenario.street.upper()}")
        print(f"\nYOU:\n{' '.join(card_code(card) for card in scenario.hero_cards)}")
        print(f"\nBoard:\n{' '.join(card_code(card) for card in scenario.board) or '(none)'}")
        print(f"\nPosition:\n{scenario.hero_position}")
        print(f"\nYour stack:\n{scenario.hero_stack}")
        print(f"\nEffective stack:\n{scenario.effective_stack}")
        print(f"\nPot:\n{scenario.pot}")
        print("\nOpponents:")
        for opponent in scenario.opponents:
            print(
                f"\n{opponent.position}\n"
                f"stack: {opponent.stack}\n"
                f"action: {opponent.status}\n"
                f"modeled profile: {opponent.profile}"
            )
        print("\nAction history:")
        for action in record.final_action_history:
            print(f"  {action.describe()}")
        print(f"\nAmount to call:\n{scenario.amount_to_call}")
        print(f"\nMinimum raise-to:\n{scenario.minimum_raise_to}")
        print(f"\nYOUR EQUITY:\n{record.equity.equity:.1%}")
        print(f"\nWin:\n{record.equity.win_probability:.1%}")
        print(f"\nTie:\n{record.equity.tie_probability:.1%}")
        print(f"\nLoss:\n{record.equity.loss_probability:.1%}")
        print(f"\nEquity simulations:\n{record.equity.simulations}")
        print("\nPLAYER DECISION")
        print(f"\nAction:\n{record.player_action.upper()}")
        if record.player_amount is not None and record.player_action in {"bet", "raise"}:
            print(f"\n{record.player_action.title()} to:\n{record.player_amount}")
        print(f"\nConfidence:\n{record.confidence_percent}%")
        print("\nACTION EVs")
        for option in evaluation.options:
            label = option.key.replace("_", " ").title()
            print(f"\n{label}:\n{option.ev:+.2f} +/- {1.96 * option.standard_error:.2f} (95% MC)")
        print(f"\nMODEL-PREFERRED ACTION:\n{evaluation.best_action.upper()}")
        if evaluation.best_amount is not None:
            print(f"\nBEST MODELED SIZE:\n{evaluation.best_amount}")
        if evaluation.preferred_size_range:
            low, high = evaluation.preferred_size_range
            print(f"\nPREFERRED SIZE REGION:\n{low}-{high}")
        print(
            "\nNEAR-EQUIVALENT OPTIONS:\n"
            + ", ".join(key.upper() for key in evaluation.near_equivalent_keys)
        )
        print(f"\nPLAYER CHOSEN EV:\n{record.chosen_ev:+.2f}")
        print(f"\nBEST EV:\n{record.best_ev:+.2f}")
        print(f"\nEV DIFFERENCE FROM BEST:\n{record.ev_regret:.2f}")
        print(f"\nEV REGRET:\n{record.ev_regret:.2f}")
        print(f"\nSIZING REGRET:\n{record.sizing_regret:.2f}")
        print(f"\nDECISION CLASSIFICATION:\n{record.decision_classification}")
        print(f"\nEXACT MODEL-PREFERRED:\n{'YES' if record.exact_preferred else 'NO'}")
        print(f"\nWITHIN ACCEPTED TOLERANCE:\n{'YES' if record.acceptable_action else 'NO'}")
        print(f"\nDIFFICULTY:\n{evaluation.difficulty}")
        print("\nMODEL ASSUMPTIONS")
        print("  Opponent cards come from profile-, position-, and action-weighted ranges.")
        print("  Check/call EV applies a street-specific equity-realization factor.")
        print("  Bet/raise EV models independent fold/continue responses and stronger calling ranges.")
        print("  No future street betting tree or equilibrium response is solved.")
        print("=" * 50)

    @staticmethod
    def print_session_summary(summary: dict) -> None:
        print("\n" + "=" * 50)
        print("POKER SESSION SUMMARY")
        print("=" * 50)
        print(
            f"\nModel-preferred actions:\n"
            f"{summary['preferred_action_count']} / {summary['rounds']}\n"
            f"\nExact model-preferred actions:\n{summary['exact_preferred_count']} / {summary['rounds']}\n"
            f"\nPreferred action family:\n{summary['preferred_action_family_count']} / {summary['rounds']}\n"
            f"\nAction accuracy:\n{summary['action_accuracy']:.1%}\n"
            f"\nAverage confidence:\n{summary['average_confidence']:.1%}\n"
            f"\nCalibration gap:\n{summary['calibration_gap']:+.1%}\n"
            f"\nBrier score:\n{summary['brier_score']:.4f}\n"
            f"\nTotal EV regret:\n{summary['total_ev_regret']:.2f} chips\n"
            f"\nAverage EV regret:\n{summary['average_ev_regret']:.2f} chips\n"
            f"\nChosen total EV:\n{summary['chosen_total_ev']:+.2f} chips\n"
            f"\nBest modeled total EV:\n{summary['best_total_ev']:+.2f} chips\n"
            f"\nValue left on the table:\n{summary['value_left_on_table']:.2f} chips\n"
            f"\nPlayer aggression frequency:\n{summary['player_aggression_frequency']:.1%}\n"
            f"\nModel-preferred aggression:\n{summary['model_aggression_frequency']:.1%}\n"
            f"\nAverage sizing regret:\n{summary['average_sizing_regret']:.2f} chips"
        )
        print("\nAction frequencies:")
        for action, frequency in summary["action_frequencies"].items():
            print(f"  {action.upper()}: {frequency:.1%}")
        if summary["observations"]:
            print("\nCautious observations:")
            for observation in summary["observations"]:
                print(f"  {observation}")
        print("\nFive decisions are a small sample; these are session-level signals, not a diagnosis.")
        print("=" * 50)
