"""Transparent, tunable opponent range model for the Poker experiment."""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
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

CALLING_RANGE_STRENGTH_SLOPE = 0.50
PRESSURE_SELECTION_SLOPE = 0.30
RANGE_STRENGTH_FOLD_ADJUSTMENT = 0.40
NEUTRAL_RANGE_STRENGTH = 0.45


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
        hero_cost: int,
        base_fold_probability: float,
    ) -> ConditionalCallingRange:
        """Condition an opponent's existing range on continuing versus this size.

        The supplied base fold probability retains the transparent profile,
        street, prior-action, and pressure assumptions from the EV model. Combo
        strength then redistributes those folds: stronger combinations continue
        more often, and larger pressure makes the continuing range more selective.
        """
        prior = self.weighted_combos(scenario, opponent)
        strengths = tuple(range_continue_strength(combo, scenario.board) for combo, _weight in prior)
        total_prior_weight = sum(weight for _combo, weight in prior)
        prior_mean = sum(
            strength * weight for strength, (_combo, weight) in zip(strengths, prior)
        ) / total_prior_weight
        pressure = hero_cost / max(1, scenario.pot)
        strength_slope = CALLING_RANGE_STRENGTH_SLOPE + PRESSURE_SELECTION_SLOPE * min(2.0, pressure)
        # A value-heavy prior range should not retain the same average fold rate
        # as an air-heavy checked range merely because both share a profile.
        range_adjusted_fold = base_fold_probability - RANGE_STRENGTH_FOLD_ADJUSTMENT * (
            prior_mean - NEUTRAL_RANGE_STRENGTH
        )

        calling: list[tuple[tuple[Card, Card], float]] = []
        expected_fold_weight = 0.0
        calling_strength_weight = 0.0
        total_call_weight = 0.0
        for (combo, prior_weight), strength in zip(prior, strengths):
            combo_fold = max(
                0.01,
                min(0.99, range_adjusted_fold + strength_slope * (prior_mean - strength)),
            )
            call_weight = prior_weight * (1.0 - combo_fold)
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
        1: 0.43,
        2: 0.62,
        3: 0.70,
        4: 0.78,
        5: 0.83,
        6: 0.90,
        7: 0.96,
        8: 1.00,
    }[score[0]]
    kicker_component = min(0.08, sum(score[1:]) / 500.0)
    category = postflop_category(combo, board)
    draw_bonus = 0.12 if category == "strong_draw" else 0.06 if category == "weak_draw" else 0.0
    return min(1.0, category_base + kicker_component + draw_bonus)


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
