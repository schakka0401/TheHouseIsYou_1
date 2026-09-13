"""Transparent, tunable opponent range model for the Poker experiment."""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
import math
import random

from game.poker_hand_evaluator import evaluate_holdem
from game.poker_models import Card, OpponentState, PokerScenario, RANK_VALUE, poker_deck


PROFILES = ("TIGHT", "BALANCED", "LOOSE", "AGGRESSIVE")

PROFILE_CONFIG = {
    "TIGHT": {"threshold": 0.60, "aggression": 0.28, "fold_base": 0.48},
    "BALANCED": {"threshold": 0.48, "aggression": 0.45, "fold_base": 0.38},
    "LOOSE": {"threshold": 0.35, "aggression": 0.42, "fold_base": 0.27},
    "AGGRESSIVE": {"threshold": 0.42, "aggression": 0.70, "fold_base": 0.31},
}

POSITION_LOOSENESS = {
    "UTG": -0.04,
    "MP": -0.02,
    "CO": 0.03,
    "BTN": 0.07,
    "SB": -0.01,
    "BB": 0.02,
}

CONTINUE_LOGIT_SLOPE = 10.0


@dataclass(frozen=True)
class ConditionalCallingRange:
    weighted_combos: tuple[tuple[tuple[Card, Card], float], ...]
    fold_probability: float
    prior_mean_strength: float
    calling_mean_strength: float


class PokerRangeModel:
    """Weighted legal two-card combos conditioned on profile and observed action.

    This is deliberately an inspectable heuristic, not a solver range. Preflop
    weights use hand-class strength, profile, and position. Postflop weights
    then reweight those combos by made-hand/draw category and the player's
    latest legal action.
    """

    def __init__(self) -> None:
        self._cache: dict[tuple, tuple[tuple[tuple[Card, Card], float], ...]] = {}

    def weighted_combos(
        self,
        scenario: PokerScenario,
        opponent: OpponentState,
    ) -> tuple[tuple[tuple[Card, Card], float], ...]:
        key = (scenario.key, opponent.position)
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        known = set(scenario.hero_cards + scenario.board)
        available = [card for card in poker_deck() if card not in known]
        weighted: list[tuple[tuple[Card, Card], float]] = []
        for combo in combinations(available, 2):
            preflop = self.preflop_weight(combo, opponent.profile, opponent.position, opponent.status)
            if preflop <= 0:
                continue
            postflop = self.postflop_action_weight(combo, scenario.board, opponent.profile, opponent.status)
            weight = preflop * postflop
            if weight > 0.0001:
                weighted.append(((combo[0], combo[1]), weight))
        if not weighted:
            raise ValueError(f"Range model produced no combos for {opponent.position}")
        result = tuple(weighted)
        self._cache[key] = result
        return result

    @staticmethod
    def preflop_weight(
        combo: tuple[Card, Card],
        profile: str,
        position: str,
        status: str,
    ) -> float:
        config = PROFILE_CONFIG[profile]
        strength = starting_hand_strength(combo)
        threshold = config["threshold"] - POSITION_LOOSENESS.get(position, 0.0)
        status_upper = status.upper()
        if "RAISED" in status_upper or "BET" in status_upper:
            threshold += 0.08 - config["aggression"] * 0.08
        elif "CALLED" in status_upper:
            threshold -= 0.04
        elif "CHECKED" in status_upper or status_upper == "WAITING":
            threshold -= 0.08
        margin = strength - threshold
        if margin < -0.20:
            return 0.0
        base = max(0.04, 0.45 + margin * 2.6)
        if ("RAISED" in status_upper or "BET" in status_upper) and margin > 0.10:
            base *= 1.8
        if profile == "AGGRESSIVE" and strength < threshold:
            base *= 1.8  # explicit bluff/semi-bluff tail
        return base

    @staticmethod
    def postflop_action_weight(
        combo: tuple[Card, Card],
        board: tuple[Card, ...],
        profile: str,
        status: str,
    ) -> float:
        if len(board) < 3:
            return 1.0
        category = postflop_category(combo, board)
        status_upper = status.upper()
        if "RAISED" in status_upper:
            if len(board) == 5:
                weights = {
                    "strong_made": 5.5,
                    "medium_made": 0.35,
                    "strong_draw": 0.0,
                    "weak_draw": 0.0,
                    "air": {"TIGHT": 0.05, "BALANCED": 0.20, "LOOSE": 0.25, "AGGRESSIVE": 0.50}[profile],
                }
            else:
                weights = {
                    "strong_made": 3.8,
                    "medium_made": 1.2,
                    "strong_draw": 2.4,
                    "weak_draw": 1.0,
                    "air": 0.70 if profile == "AGGRESSIVE" else 0.18,
                }
        elif "BET" in status_upper:
            if len(board) == 5:
                weights = {
                    "strong_made": 4.0,
                    "medium_made": 0.75,
                    "strong_draw": 0.0,
                    "weak_draw": 0.0,
                    "air": {"TIGHT": 0.12, "BALANCED": 0.45, "LOOSE": 0.55, "AGGRESSIVE": 0.85}[profile],
                }
            else:
                weights = {
                    "strong_made": 3.2,
                    "medium_made": 1.5,
                    "strong_draw": 2.2,
                    "weak_draw": 1.2,
                    "air": 0.75 if profile == "AGGRESSIVE" else 0.25,
                }
        elif "CALLED" in status_upper:
            weights = {
                "strong_made": 1.8,
                "medium_made": 1.8,
                "strong_draw": 2.0,
                "weak_draw": 1.3,
                "air": 0.18,
            }
        elif "CHECKED" in status_upper:
            weights = {
                "strong_made": 0.70,
                "medium_made": 1.15,
                "strong_draw": 1.0,
                "weak_draw": 1.1,
                "air": 1.35,
            }
        else:
            weights = {
                "strong_made": 1.0,
                "medium_made": 1.0,
                "strong_draw": 1.0,
                "weak_draw": 1.0,
                "air": 1.0,
            }
        return weights[category]

    def sample_combo(
        self,
        scenario: PokerScenario,
        opponent: OpponentState,
        blocked: set[Card],
        rng: random.Random,
    ) -> tuple[Card, Card]:
        legal = [(combo, weight) for combo, weight in self.weighted_combos(scenario, opponent)
                 if combo[0] not in blocked and combo[1] not in blocked]
        if not legal:
            raise ValueError("No collision-free opponent combo remains")
        combos, weights = zip(*legal)
        return rng.choices(combos, weights=weights, k=1)[0]

    def conditional_calling_range(
        self,
        scenario: PokerScenario,
        opponent: OpponentState,
        raise_to: int,
        behavior_bias: float = 0.0,
    ) -> ConditionalCallingRange:
        """Condition an opponent's existing range on continuing versus this size.

        Every prior combo receives its own continuation probability.  The main
        inputs are that combo's made-hand/draw strength and its price; profile,
        prior action, street, and stack commitment shift the threshold.  A
        positive behavior bias represents a somewhat wider/more willing caller.
        """
        prior = self.weighted_combos(scenario, opponent)
        strengths = tuple(range_continue_strength(combo, scenario.board) for combo, _weight in prior)
        total_prior_weight = sum(weight for _combo, weight in prior)
        prior_mean = sum(
            strength * weight for strength, (_combo, weight) in zip(strengths, prior)
        ) / total_prior_weight
        hero_cost = max(0, raise_to - scenario.hero_contribution)
        call_cost = min(max(0, raise_to - opponent.contribution), opponent.stack)
        pot_after_call = scenario.pot + hero_cost + call_cost
        pot_odds = call_cost / max(1, pot_after_call)
        pressure = hero_cost / max(1, scenario.pot)
        stack_fraction = call_cost / max(1, opponent.stack)
        threshold = _continue_threshold(
            scenario, opponent, pot_odds, pressure, stack_fraction
        )

        calling: list[tuple[tuple[Card, Card], float]] = []
        expected_fold_weight = 0.0
        calling_strength_weight = 0.0
        total_call_weight = 0.0
        for (combo, prior_weight), strength in zip(prior, strengths):
            continue_probability = _logistic(
                CONTINUE_LOGIT_SLOPE * (strength - threshold) + behavior_bias
            )
            # Preserve small profile-dependent tails without allowing any hand
            # to become an automatic call or fold.
            tail = 0.025 if opponent.profile in {"LOOSE", "AGGRESSIVE"} else 0.012
            floor = max(0.001, tail / (1.0 + 1.5 * pressure))
            ceiling = 0.992 if opponent.profile != "TIGHT" else 0.982
            continue_probability = max(floor, min(ceiling, continue_probability))
            combo_fold = 1.0 - continue_probability
            call_weight = prior_weight * continue_probability
            expected_fold_weight += prior_weight * combo_fold
            if call_weight > 0.000001:
                calling.append((combo, call_weight))
                total_call_weight += call_weight
                calling_strength_weight += strength * call_weight
        if not calling or total_call_weight <= 0:
            raise ValueError(f"Conditional calling range is empty for {opponent.position}")
        return ConditionalCallingRange(
            weighted_combos=tuple(calling),
            fold_probability=expected_fold_weight / total_prior_weight,
            prior_mean_strength=prior_mean,
            calling_mean_strength=calling_strength_weight / total_call_weight,
        )


def _continue_threshold(
    scenario: PokerScenario,
    opponent: OpponentState,
    pot_odds: float,
    pressure: float,
    stack_fraction: float,
) -> float:
    """Required 0-1 range strength for a neutral 50% continuation chance."""
    if scenario.street == "preflop":
        threshold = 0.55 + 0.45 * pot_odds + 0.08 * stack_fraction
    else:
        threshold = 0.30 + 0.55 * pot_odds + 0.10 * stack_fraction
    threshold += 0.055 * math.log1p(min(8.0, pressure))
    threshold += {"TIGHT": 0.045, "BALANCED": 0.0, "LOOSE": -0.050, "AGGRESSIVE": -0.035}[opponent.profile]
    status = opponent.status.upper()
    if "RAISED" in status:
        threshold -= 0.085
    elif "BET" in status:
        threshold -= 0.065
    elif "CALLED" in status:
        threshold -= 0.040
    elif "CHECKED" in status or status == "WAITING":
        threshold += 0.025
    if scenario.street == "river":
        threshold += 0.025
    return max(0.12, min(0.94, threshold))


def _logistic(value: float) -> float:
    if value >= 0:
        return 1.0 / (1.0 + math.exp(-value))
    exp_value = math.exp(value)
    return exp_value / (1.0 + exp_value)


def starting_hand_strength(combo: tuple[Card, Card]) -> float:
    (rank_a, suit_a), (rank_b, suit_b) = combo
    high, low = sorted((RANK_VALUE[rank_a], RANK_VALUE[rank_b]), reverse=True)
    if high == low:
        return min(1.0, 0.52 + high / 28.0)
    suited_bonus = 0.06 if suit_a == suit_b else 0.0
    gap = high - low
    connector_bonus = 0.07 if gap == 1 else 0.035 if gap == 2 else 0.0
    broadway_bonus = 0.08 if high >= 11 and low >= 10 else 0.0
    ace_bonus = 0.06 if high == 14 else 0.0
    gap_penalty = max(0, gap - 3) * 0.025
    return max(0.0, min(1.0, (high + low) / 32.0 + suited_bonus + connector_bonus + broadway_bonus + ace_bonus - gap_penalty))


def postflop_category(combo: tuple[Card, Card], board: tuple[Card, ...]) -> str:
    score = evaluate_holdem(combo, board)
    if score[0] >= 2:
        return "strong_made"
    if score[0] == 1:
        return "medium_made"
    flush_draw, straight_draw = _draws(combo + board)
    if flush_draw and straight_draw:
        return "strong_draw"
    if flush_draw or straight_draw:
        return "weak_draw"
    return "air"


def range_continue_strength(combo: tuple[Card, Card], board: tuple[Card, ...]) -> float:
    """Return an inspectable 0-1 ordering score for call-range selection."""
    if len(board) < 3:
        return starting_hand_strength(combo)
    score = evaluate_holdem(combo, board)
    category_base = {
        0: 0.14,
        1: 0.38,
        2: 0.62,
        3: 0.70,
        4: 0.78,
        5: 0.83,
        6: 0.90,
        7: 0.96,
        8: 1.00,
    }[score[0]]
    kicker_component = min(0.08, sum(score[1:]) / 500.0)
    if score[0] == 1:
        pair_rank = score[1]
        board_values = sorted({RANK_VALUE[rank] for rank, _suit in board}, reverse=True)
        board_overcards = sum(value > pair_rank for value in board_values)
        if pair_rank not in board_values:  # pocket overpair or underpair
            pair_adjustment = 0.13 if pair_rank > max(board_values) else -0.01 * board_overcards
        else:
            pair_adjustment = max(-0.025, 0.10 - 0.045 * board_overcards)
        kicker_component += pair_adjustment
    category = postflop_category(combo, board)
    if category == "strong_draw":
        return max(0.54, min(0.68, category_base + kicker_component + 0.34))
    if category == "weak_draw":
        return max(0.39, min(0.55, category_base + kicker_component + 0.22))
    return min(1.0, category_base + kicker_component)


def _draws(cards: tuple[Card, ...]) -> tuple[bool, bool]:
    if len(cards) >= 7:
        return False, False
    suit_counts: dict[str, int] = {}
    for _rank, suit in cards:
        suit_counts[suit] = suit_counts.get(suit, 0) + 1
    flush_draw = max(suit_counts.values(), default=0) == 4

    values = {RANK_VALUE[rank] for rank, _suit in cards}
    if 14 in values:
        values.add(1)
    straight_draw = any(len(values.intersection(range(start, start + 5))) == 4 for start in range(1, 11))
    return flush_draw, straight_draw
