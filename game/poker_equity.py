"""Collision-safe Monte Carlo equity estimation against modeled ranges."""
from __future__ import annotations

from itertools import accumulate
import random

from game.poker_hand_evaluator import evaluate_holdem, showdown_share
from game.poker_models import Card, EquityResult, PokerScenario, poker_deck
from game.poker_ranges import PokerRangeModel


EQUITY_SIMULATIONS = 10_000


class PokerEquityEstimator:
    def __init__(
        self,
        range_model: PokerRangeModel | None = None,
        simulations: int = EQUITY_SIMULATIONS,
        seed: int | None = None,
    ) -> None:
        if simulations <= 0:
            raise ValueError("Equity simulations must be positive")
        self.range_model = range_model or PokerRangeModel()
        self.simulations = simulations
        self.random = random.Random(seed)
        self._cache: dict[tuple, EquityResult] = {}

    def estimate(self, scenario: PokerScenario) -> EquityResult:
        cache_key = (scenario.key, self.simulations)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        weighted_ranges = tuple(
            (opponent.position, self.range_model.weighted_combos(scenario, opponent))
            for opponent in scenario.active_opponents
        )
        result = self.estimate_weighted_ranges(scenario, weighted_ranges, self.simulations)
        self._cache[cache_key] = result
        return result

    def estimate_weighted_ranges(
        self,
        scenario: PokerScenario,
        weighted_ranges: tuple[
            tuple[str, tuple[tuple[tuple[Card, Card], float], ...]], ...
        ],
        simulations: int,
    ) -> EquityResult:
        """Estimate equity against supplied ranges, used for size-conditioned calls."""
        if simulations <= 0:
            raise ValueError("Equity simulations must be positive")
        prepared_ranges = []
        for position, weighted in weighted_ranges:
            combos = tuple(combo for combo, _weight in weighted)
            weights = tuple(weight for _combo, weight in weighted)
            prepared_ranges.append((position, combos, tuple(accumulate(weights)), weights))

        known = set(scenario.hero_cards + scenario.board)
        wins = ties = losses = 0
        total_share = 0.0
        total_share_squared = 0.0
        complete_board_count = 5 - len(scenario.board)

        for _ in range(simulations):
            blocked = set(known)
            sampled_hands: list[tuple[Card, Card]] = []
            for position, combos, cumulative, weights in prepared_ranges:
                combo = self._sample_collision_free(position, combos, cumulative, weights, blocked)
                sampled_hands.append(combo)
                blocked.update(combo)

            remaining = [card for card in poker_deck() if card not in blocked]
            runout = tuple(self.random.sample(remaining, complete_board_count))
            complete_board = scenario.board + runout
            hero_score = evaluate_holdem(scenario.hero_cards, complete_board)
            opponent_scores = [evaluate_holdem(hand, complete_board) for hand in sampled_hands]
            share = showdown_share(hero_score, opponent_scores)
            total_share += share
            total_share_squared += share * share
            if share == 1.0:
                wins += 1
            elif share > 0.0:
                ties += 1
            else:
                losses += 1

        mean_share = total_share / simulations
        share_variance = max(0.0, total_share_squared / simulations - mean_share * mean_share)
        return EquityResult(
            equity=mean_share,
            win_probability=wins / simulations,
            tie_probability=ties / simulations,
            loss_probability=losses / simulations,
            simulations=simulations,
            standard_error=(share_variance / simulations) ** 0.5,
        )

    def sample_opponent_hands(self, scenario: PokerScenario) -> dict[str, tuple[Card, Card]]:
        """Public diagnostic helper used to prove sampled ranges never collide."""
        blocked = set(scenario.hero_cards + scenario.board)
        result: dict[str, tuple[Card, Card]] = {}
        for opponent in scenario.active_opponents:
            combo = self.range_model.sample_combo(scenario, opponent, blocked, self.random)
            result[opponent.position] = combo
            blocked.update(combo)
        return result

    def _sample_collision_free(
        self,
        position: str,
        combos: tuple[tuple[Card, Card], ...],
        cumulative: tuple[float, ...],
        weights: tuple[float, ...],
        blocked: set[Card],
    ) -> tuple[Card, Card]:
        for _ in range(20):
            combo = self.random.choices(combos, cum_weights=cumulative, k=1)[0]
            if combo[0] not in blocked and combo[1] not in blocked:
                return combo
        legal = [(combo, weight) for combo, weight in zip(combos, weights)
                 if combo[0] not in blocked and combo[1] not in blocked]
        if not legal:
            raise ValueError(f"No collision-free modeled range remains for {position}")
        legal_combos, legal_weights = zip(*legal)
        return self.random.choices(legal_combos, weights=legal_weights, k=1)[0]
