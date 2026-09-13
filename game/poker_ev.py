"""Explicit approximate action-EV model for single-decision Poker snapshots."""
from __future__ import annotations

from itertools import product
import math

from game.poker_equity import PokerEquityEstimator
from game.poker_models import (
    ActionOption,
    AggressiveActionTrace,
    AggressiveBranch,
    EquityResult,
    OpponentResponse,
    OpponentState,
    PokerActionEvaluation,
    PokerScenario,
)
from game.poker_ranges import PROFILE_CONFIG, PokerRangeModel


RAISE_EV_TOLERANCE = 0.03
NEAR_EQUAL_EV_TOLERANCE = 0.02
AGGRESSIVE_BRANCH_SIMULATIONS = 1_500
SENSITIVITY_BRANCH_SIMULATIONS = 300
SENSITIVITY_BEHAVIOR_BIASES = (-0.45, 0.45)

REALIZATION_BY_STREET = {
    "preflop": 0.72,
    "flop": 0.79,
    "turn": 0.88,
    "river": 1.00,
}


class PokerEVModel:
    """Rank actions using explicit ranges and size-conditioned responses.

    This is not GTO. Check/call branches use showdown equity multiplied by a
    street-dependent realization factor. Each bet/raise size conditions every
    opponent's range on calling that exact pressure, evaluates every possible
    fold/continue branch, and estimates Hero equity against those callers.
    """

    def __init__(
        self,
        range_model: PokerRangeModel | None = None,
        branch_simulations: int = AGGRESSIVE_BRANCH_SIMULATIONS,
        seed: int | None = None,
        sensitivity: bool = True,
    ) -> None:
        if branch_simulations <= 0:
            raise ValueError("Aggressive branch simulations must be positive")
        self.range_model = range_model or PokerRangeModel()
        self.branch_simulations = branch_simulations
        self.sensitivity = sensitivity
        self.conditional_equity = PokerEquityEstimator(
            self.range_model,
            simulations=branch_simulations,
            seed=seed,
        )

    def evaluate(self, scenario: PokerScenario, equity: EquityResult) -> PokerActionEvaluation:
        options: list[ActionOption] = []
        realization = REALIZATION_BY_STREET[scenario.street]
        for action in scenario.legal_actions:
            if action == "fold":
                options.append(ActionOption("fold", "fold", None, 0.0))
            elif action == "check":
                scale = scenario.pot * realization
                options.append(ActionOption(
                    "check", "check", None, self._check_ev(scenario, equity), equity.standard_error * scale
                ))
            elif action == "call":
                scale = (scenario.pot + scenario.amount_to_call) * realization
                options.append(ActionOption(
                    "call",
                    "call",
                    scenario.amount_to_call,
                    self._call_ev(scenario, equity),
                    equity.standard_error * scale,
                ))
            elif action == "bet":
                options.extend(
                    self._aggressive_option(scenario, amount, "bet")
                    for amount in scenario.candidate_bet_sizes
                )
            elif action == "raise":
                options.extend(
                    self._aggressive_option(scenario, amount, "raise")
                    for amount in scenario.candidate_raise_sizes
                )
        if not options:
            raise ValueError("Poker scenario has no legal action options")

        ordered = sorted(options, key=lambda candidate: candidate.ev, reverse=True)
        best = ordered[0]
        margin = best.ev - ordered[1].ev if len(ordered) > 1 else abs(best.ev)
        normalized_margin = margin / max(1, scenario.pot if scenario.pot else scenario.big_blind)
        difficulty = "HARD" if normalized_margin < 0.05 else "MEDIUM" if normalized_margin < 0.16 else "EASY"

        near_equivalent = tuple(
            option.key for option in options if self._near_equal(best, option, scenario.pot)
        )
        sensitivity_best_keys = [best.key]
        if self.sensitivity and any(option.action in {"bet", "raise"} for option in options):
            sensitivity_simulations = min(SENSITIVITY_BRANCH_SIMULATIONS, self.branch_simulations)
            for behavior_bias in SENSITIVITY_BEHAVIOR_BIASES:
                varied = [
                    self._aggressive_option(
                        scenario,
                        option.amount,
                        option.action,
                        behavior_bias=behavior_bias,
                        simulations=sensitivity_simulations,
                    )
                    if option.action in {"bet", "raise"} and option.amount is not None
                    else option
                    for option in options
                ]
                sensitivity_best_keys.append(max(varied, key=lambda candidate: candidate.ev).key)
        model_sensitive = len({self._decision_family(key) for key in sensitivity_best_keys}) > 1
        preferred_range = None
        if best.action in {"bet", "raise"}:
            size_tolerance = max(1.0, scenario.pot * RAISE_EV_TOLERANCE)
            near_sizes: list[int] = []
            for option in options:
                if (
                    option.action == best.action
                    and option.amount is not None
                    and (best.ev - option.ev <= size_tolerance or option.key in near_equivalent)
                ):
                    near_sizes.append(option.amount)
            assert best.amount is not None
            preferred_range = (
                (min(near_sizes), max(near_sizes))
                if near_sizes else (best.amount, best.amount)
            )

        return PokerActionEvaluation(
            options=tuple(options),
            best_key=best.key,
            best_action=best.action,
            best_amount=best.amount,
            preferred_size_range=preferred_range,
            best_ev=best.ev,
            decision_margin=margin,
            difficulty=difficulty,
            near_equivalent_keys=near_equivalent,
            sensitivity_best_keys=tuple(sensitivity_best_keys),
            model_sensitive=model_sensitive,
        )

    @staticmethod
    def _near_equal(best: ActionOption, option: ActionOption, pot: int) -> bool:
        practical_tolerance = max(1.0, pot * NEAR_EQUAL_EV_TOLERANCE)
        statistical_tolerance = 1.96 * math.hypot(best.standard_error, option.standard_error)
        return best.ev - option.ev <= max(practical_tolerance, statistical_tolerance)

    @staticmethod
    def _check_ev(scenario: PokerScenario, equity: EquityResult) -> float:
        return equity.equity * scenario.pot * REALIZATION_BY_STREET[scenario.street]

    @staticmethod
    def _call_ev(scenario: PokerScenario, equity: EquityResult) -> float:
        cost = scenario.amount_to_call
        pot_after_call = scenario.pot + cost
        return equity.equity * pot_after_call * REALIZATION_BY_STREET[scenario.street] - cost

    def _aggressive_option(
        self,
        scenario: PokerScenario,
        raise_to: int,
        action: str,
        behavior_bias: float = 0.0,
        simulations: int | None = None,
    ) -> ActionOption:
        trace, standard_error = self._aggressive_trace(
            scenario, raise_to, behavior_bias, simulations
        )
        return ActionOption(
            key=self._sized_key(action, raise_to, scenario),
            action=action,
            amount=raise_to,
            ev=sum(branch.weighted_ev for branch in trace.branches),
            standard_error=standard_error,
            aggressive_trace=trace,
        )

    def _aggressive_trace(
        self,
        scenario: PokerScenario,
        raise_to: int,
        behavior_bias: float = 0.0,
        simulations: int | None = None,
    ) -> tuple[AggressiveActionTrace, float]:
        simulations = simulations or self.branch_simulations
        hero_cost = max(0, raise_to - scenario.hero_contribution)
        opponents = scenario.active_opponents
        realization = REALIZATION_BY_STREET[scenario.street]
        conditional_ranges = []
        responses: list[OpponentResponse] = []
        for opponent in opponents:
            conditioned = self.range_model.conditional_calling_range(
                scenario, opponent, raise_to, behavior_bias
            )
            call_cost = min(max(0, raise_to - opponent.contribution), opponent.stack)
            pot_odds = call_cost / max(1, scenario.pot + hero_cost + call_cost)
            conditional_ranges.append(conditioned)
            responses.append(OpponentResponse(
                position=opponent.position,
                profile=opponent.profile,
                prior_status=opponent.status,
                fold_probability=conditioned.fold_probability,
                prior_mean_strength=conditioned.prior_mean_strength,
                calling_mean_strength=conditioned.calling_mean_strength,
                pot_odds=pot_odds,
                call_cost=call_cost,
            ))

        branches: list[AggressiveBranch] = []
        uncertainty_variance = 0.0
        for folds in product((False, True), repeat=len(opponents)):
            branch_probability = 1.0
            continuing_indices: list[int] = []
            for index, folded in enumerate(folds):
                fold_probability = responses[index].fold_probability
                branch_probability *= fold_probability if folded else 1.0 - fold_probability
                if not folded:
                    continuing_indices.append(index)
            continuing_positions = tuple(opponents[index].position for index in continuing_indices)
            if not continuing_indices:
                final_pot = scenario.pot
                called_equity = None
                equity_standard_error = 0.0
                branch_ev = float(scenario.pot)
            else:
                weighted_ranges = tuple(
                    (opponents[index].position, conditional_ranges[index].weighted_combos)
                    for index in continuing_indices
                )
                called = self.conditional_equity.estimate_weighted_ranges(
                    scenario, weighted_ranges, simulations
                )
                caller_contributions = sum(
                    min(max(0, raise_to - opponents[index].contribution), opponents[index].stack)
                    for index in continuing_indices
                )
                final_pot = scenario.pot + hero_cost + caller_contributions
                called_equity = called.equity
                equity_standard_error = called.standard_error
                branch_realization = 1.0 if hero_cost >= scenario.hero_stack else realization
                branch_ev = called_equity * final_pot * branch_realization - hero_cost
                uncertainty_variance += (
                    branch_probability * final_pot * branch_realization * equity_standard_error
                ) ** 2
            weighted_ev = branch_probability * branch_ev
            branches.append(AggressiveBranch(
                continuing_positions=continuing_positions,
                probability=branch_probability,
                called_equity=called_equity,
                called_equity_standard_error=equity_standard_error,
                final_pot=final_pot,
                branch_ev=branch_ev,
                weighted_ev=weighted_ev,
            ))

        trace = AggressiveActionTrace(
            raise_to=raise_to,
            pot_before=scenario.pot,
            hero_cost=hero_cost,
            pressure=hero_cost / max(1, scenario.pot),
            simulations_per_called_branch=simulations,
            opponent_responses=tuple(responses),
            branches=tuple(branches),
        )
        return trace, math.sqrt(uncertainty_variance)

    def fold_probability(self, opponent: OpponentState, scenario: PokerScenario, hero_cost: int) -> float:
        """Range-composition fold rate retained as a public audit helper."""
        raise_to = scenario.hero_contribution + hero_cost
        return self.range_model.conditional_calling_range(
            scenario, opponent, raise_to
        ).fold_probability

    @staticmethod
    def _decision_family(key: str) -> str:
        if key == "all_in":
            return "all_in"
        if key.startswith("raise_to_"):
            return "raise"
        if key.startswith("bet_to_"):
            return "bet"
        return key

    @staticmethod
    def _sized_key(action: str, amount: int, scenario: PokerScenario) -> str:
        maximum = scenario.hero_contribution + scenario.hero_stack
        return "all_in" if amount == maximum else f"{action}_to_{amount}"
