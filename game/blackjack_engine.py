"""Exact finite-deck Blackjack decision evaluation and scenario generation.

Only HIT and STAND are available. The dealer stands on every 17, aces count as
11 when possible, and there are no splits, doubles, surrender, insurance, or
special natural-blackjack payout. Every visible card is removed from the deck.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import random


Card = tuple[str, str]
RANKS = ("2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A")
SUITS = ("clubs", "diamonds", "hearts", "spades")
RANK_INDEX = {rank: index for index, rank in enumerate(RANKS)}
RANK_HARD_VALUES = (2, 3, 4, 5, 6, 7, 8, 9, 10, 10, 10, 10, 1)

VERY_OBVIOUS_MARGIN = 0.30
EASY_MARGIN = 0.18
MEDIUM_MARGIN = 0.06

# These rank-level states were classified with the exact evaluator below. Using
# a validated bank avoids searching hundreds of candidates while Pygame's main
# thread is waiting. Suits are assigned from a real deck at runtime, so every
# visible state still has valid finite-deck composition.
SCENARIO_BLUEPRINTS: dict[str, tuple[tuple[tuple[str, ...], str], ...]] = {
    "EASY": (
        (("4", "8"), "7"),
        (("7", "7", "2"), "4"),
        (("A", "4", "4"), "3"),
        (("2", "6"), "6"),
        (("4", "4"), "J"),
        (("5", "Q"), "4"),
        (("Q", "5"), "3"),
        (("7", "7"), "4"),
        (("2", "2", "3", "3", "4"), "6"),
        (("A", "2", "2", "2", "3", "3"), "5"),
    ),
    "MEDIUM": (
        (("8", "6"), "7"),
        (("5", "9"), "K"),
        (("2", "Q"), "2"),
        (("5", "2", "Q"), "8"),
        (("J", "4"), "Q"),
        (("8", "5", "2"), "8"),
        (("7", "5", "A"), "2"),
        (("J", "5"), "8"),
        (("4", "K"), "7"),
        (("J", "3"), "4"),
        (("2", "8", "4"), "A"),
        (("5", "9", "2"), "7"),
        (("4", "K"), "4"),
        (("A", "4", "9"), "A"),
        (("5", "8"), "6"),
        (("6", "8"), "3"),
        (("5", "9"), "3"),
        (("8", "6"), "10"),
        (("2", "2", "3", "3", "4"), "8"),
        (("A", "2", "2", "3", "4"), "6"),
        (("2", "2", "2", "3", "3", "4"), "7"),
    ),
    "HARD": (
        (("7", "5"), "2"),
        (("3", "Q", "3"), "Q"),
        (("2", "J"), "4"),
        (("K", "6"), "J"),
        (("6", "7", "A"), "J"),
        (("A", "7"), "Q"),
        (("8", "4", "A", "2"), "Q"),
        (("A", "7", "8"), "J"),
        (("K", "2"), "4"),
        (("6", "A", "A"), "6"),
        (("K", "3", "3"), "8"),
        (("Q", "5"), "9"),
        (("A", "2", "2", "3", "4"), "3"),
        (("A", "2", "2", "2", "3", "3"), "2"),
        (("2", "2", "2", "3", "3", "4"), "10"),
    ),
}


@dataclass(frozen=True)
class Scenario:
    player_cards: tuple[Card, ...]
    dealer_upcard: Card

    @property
    def key(self) -> tuple[str, ...]:
        # Suits do not affect HIT/STAND EV, but rank multiplicity does.
        return tuple(sorted(rank for rank, _ in self.player_cards)) + (self.dealer_upcard[0],)


@dataclass(frozen=True)
class SimulationStats:
    """Exact outcome probabilities; retained name for compatibility."""

    win_probability: float
    loss_probability: float
    push_probability: float

    @property
    def ev(self) -> float:
        return self.win_probability - self.loss_probability


def card_value(rank: str) -> int:
    if rank in {"J", "Q", "K"}:
        return 10
    if rank == "A":
        return 11
    return int(rank)


def hand_value(cards: list[Card] | tuple[Card, ...]) -> tuple[int, bool]:
    hard_total = sum(RANK_HARD_VALUES[RANK_INDEX[rank]] for rank, _ in cards)
    aces = sum(rank == "A" for rank, _ in cards)
    return _best_total(hard_total, aces)


def _hand_state(cards: list[Card] | tuple[Card, ...]) -> tuple[int, int]:
    return (
        sum(RANK_HARD_VALUES[RANK_INDEX[rank]] for rank, _ in cards),
        sum(rank == "A" for rank, _ in cards),
    )


def _best_total(hard_total: int, aces: int) -> tuple[int, bool]:
    soft = aces > 0 and hard_total + 10 <= 21
    return hard_total + (10 if soft else 0), soft


def _add_rank(hard_total: int, aces: int, rank_index: int) -> tuple[int, int]:
    return hard_total + RANK_HARD_VALUES[rank_index], aces + int(RANKS[rank_index] == "A")


def _terminal_stats(player_total: int, dealer_total: int) -> SimulationStats:
    if dealer_total > 21 or player_total > dealer_total:
        return SimulationStats(1.0, 0.0, 0.0)
    if player_total < dealer_total:
        return SimulationStats(0.0, 1.0, 0.0)
    return SimulationStats(0.0, 0.0, 1.0)


class BlackjackEngine:
    """Memoized exact evaluator for one-deck HIT/STAND decisions."""

    def __init__(self, seed: int | None = None, simulations: int | None = None):
        # ``simulations`` remains accepted so older callers do not break. It is
        # intentionally unused: decision EV is exact.
        self.random = random.Random(seed)
        self.cache: dict[tuple[str, ...], dict[str, SimulationStats]] = {}

    @staticmethod
    def deck() -> list[Card]:
        return [(rank, suit) for rank in RANKS for suit in SUITS]

    @staticmethod
    def difficulty(margin: float) -> str:
        if margin >= VERY_OBVIOUS_MARGIN:
            return "VERY_OBVIOUS"
        if margin >= EASY_MARGIN:
            return "EASY"
        if margin >= MEDIUM_MARGIN:
            return "MEDIUM"
        return "HARD"

    @staticmethod
    def _decrement(counts: tuple[int, ...], rank_index: int) -> tuple[int, ...]:
        mutable = list(counts)
        mutable[rank_index] -= 1
        return tuple(mutable)

    @staticmethod
    def _weighted(branches: list[tuple[float, SimulationStats]]) -> SimulationStats:
        return SimulationStats(
            sum(probability * stats.win_probability for probability, stats in branches),
            sum(probability * stats.loss_probability for probability, stats in branches),
            sum(probability * stats.push_probability for probability, stats in branches),
        )

    def _remaining_counts(self, scenario: Scenario) -> tuple[int, ...]:
        visible = list(scenario.player_cards) + [scenario.dealer_upcard]
        if len(scenario.player_cards) < 2:
            raise ValueError("A decision scenario needs at least two player cards")
        if len(visible) != len(set(visible)):
            raise ValueError("A visible card appears more than once")
        counts = [4] * len(RANKS)
        for rank, suit in visible:
            if rank not in RANK_INDEX or suit not in SUITS:
                raise ValueError(f"Invalid card: {(rank, suit)!r}")
            counts[RANK_INDEX[rank]] -= 1
            if counts[RANK_INDEX[rank]] < 0:
                raise ValueError(f"Impossible visible-card multiplicity for {rank}")
        total, _ = hand_value(scenario.player_cards)
        if total >= 21:
            raise ValueError("Decision scenarios must have a live total below 21")
        return tuple(counts)

    @lru_cache(maxsize=None)
    def _dealer_play(
        self,
        player_total: int,
        dealer_hard_total: int,
        dealer_aces: int,
        counts: tuple[int, ...],
    ) -> SimulationStats:
        dealer_total, _ = _best_total(dealer_hard_total, dealer_aces)
        if dealer_total >= 17 or not sum(counts):
            return _terminal_stats(player_total, dealer_total)
        remaining = sum(counts)
        branches = []
        for rank_index, count in enumerate(counts):
            if not count:
                continue
            next_hard, next_aces = _add_rank(dealer_hard_total, dealer_aces, rank_index)
            branches.append((
                count / remaining,
                self._dealer_play(
                    player_total,
                    next_hard,
                    next_aces,
                    self._decrement(counts, rank_index),
                ),
            ))
        return self._weighted(branches)

    @lru_cache(maxsize=None)
    def _stand_stats(
        self,
        player_hard_total: int,
        player_aces: int,
        dealer_rank_index: int,
        counts: tuple[int, ...],
    ) -> SimulationStats:
        player_total, _ = _best_total(player_hard_total, player_aces)
        dealer_hard, dealer_aces = _add_rank(0, 0, dealer_rank_index)
        remaining = sum(counts)
        if not remaining:
            dealer_total, _ = _best_total(dealer_hard, dealer_aces)
            return _terminal_stats(player_total, dealer_total)
        branches = []
        # The first dealer draw is the hidden card, even when the upcard alone
        # would look like a standing total.
        for rank_index, count in enumerate(counts):
            if not count:
                continue
            hidden_hard, hidden_aces = _add_rank(dealer_hard, dealer_aces, rank_index)
            branches.append((
                count / remaining,
                self._dealer_play(
                    player_total,
                    hidden_hard,
                    hidden_aces,
                    self._decrement(counts, rank_index),
                ),
            ))
        return self._weighted(branches)

    @lru_cache(maxsize=None)
    def _hit_stats(
        self,
        player_hard_total: int,
        player_aces: int,
        dealer_rank_index: int,
        counts: tuple[int, ...],
    ) -> SimulationStats:
        remaining = sum(counts)
        if not remaining:
            return self._stand_stats(player_hard_total, player_aces, dealer_rank_index, counts)
        branches = []
        for rank_index, count in enumerate(counts):
            if not count:
                continue
            next_hard, next_aces = _add_rank(player_hard_total, player_aces, rank_index)
            next_counts = self._decrement(counts, rank_index)
            next_total, _ = _best_total(next_hard, next_aces)
            continuation = (
                SimulationStats(0.0, 1.0, 0.0)
                if next_total > 21
                else self._optimal_continuation(next_hard, next_aces, dealer_rank_index, next_counts)
            )
            branches.append((count / remaining, continuation))
        return self._weighted(branches)

    @lru_cache(maxsize=None)
    def _optimal_continuation(
        self,
        player_hard_total: int,
        player_aces: int,
        dealer_rank_index: int,
        counts: tuple[int, ...],
    ) -> SimulationStats:
        stand = self._stand_stats(player_hard_total, player_aces, dealer_rank_index, counts)
        hit = self._hit_stats(player_hard_total, player_aces, dealer_rank_index, counts)
        return hit if hit.ev > stand.ev else stand

    def evaluate(self, scenario: Scenario) -> dict[str, SimulationStats]:
        cached = self.cache.get(scenario.key)
        if cached is not None:
            return cached
        counts = self._remaining_counts(scenario)
        player_hard, player_aces = _hand_state(scenario.player_cards)
        dealer_rank_index = RANK_INDEX[scenario.dealer_upcard[0]]
        stats = {
            "hit": self._hit_stats(player_hard, player_aces, dealer_rank_index, counts),
            "stand": self._stand_stats(player_hard, player_aces, dealer_rank_index, counts),
        }
        self.cache[scenario.key] = stats
        return stats

    def sample_outcome(self, stats: SimulationStats) -> str:
        draw = self.random.random()
        if draw < stats.win_probability:
            return "win"
        if draw < stats.win_probability + stats.loss_probability:
            return "loss"
        return "push"

    def resolve(self, scenario: Scenario, action: str) -> str:
        """Sample one casino outcome from the chosen action's exact distribution."""
        return self.sample_outcome(self.evaluate(scenario)[action])

    def _random_scenario(self) -> Scenario:
        deck = self.deck()
        self.random.shuffle(deck)
        hand_size = self.random.choices((2, 3, 4, 5, 6), weights=(24, 32, 28, 12, 4))[0]
        player_cards = tuple(deck.pop() for _ in range(hand_size))
        return Scenario(player_cards, deck.pop())

    def _scenario_from_blueprint(self, player_ranks: tuple[str, ...], dealer_rank: str) -> Scenario:
        available = {
            rank: [(rank, suit) for suit in SUITS]
            for rank in RANKS
        }
        for cards in available.values():
            self.random.shuffle(cards)
        player_cards = tuple(available[rank].pop() for rank in player_ranks)
        dealer_upcard = available[dealer_rank].pop()
        return Scenario(player_cards, dealer_upcard)

    def generate_scenario(
        self,
        target: str | None = None,
        used: set[tuple[str, ...]] | None = None,
    ) -> tuple[Scenario, dict[str, SimulationStats], str]:
        """Generate a legal decision state in the requested exact-EV category."""
        used = used or set()
        if target in SCENARIO_BLUEPRINTS:
            blueprints = list(SCENARIO_BLUEPRINTS[target])
            self.random.shuffle(blueprints)
            for player_ranks, dealer_rank in blueprints:
                scenario = self._scenario_from_blueprint(player_ranks, dealer_rank)
                if scenario.key in used:
                    continue
                player_total, _ = hand_value(scenario.player_cards)
                if player_total >= 21:
                    continue
                stats = self.evaluate(scenario)
                margin = abs(stats["hit"].ev - stats["stand"].ev)
                if margin >= VERY_OBVIOUS_MARGIN:
                    continue
                difficulty = self.difficulty(margin)
                if difficulty == target:
                    return scenario, stats, difficulty

        # Keep a fully dynamic fallback for callers requesting no category and
        # for future threshold changes that invalidate a blueprint.
        fallback: tuple[Scenario, dict[str, SimulationStats], str] | None = None
        target_order = {"HARD": 0, "MEDIUM": 1, "EASY": 2, "VERY_OBVIOUS": 3}
        best_distance = float("inf")
        for _ in range(600):
            scenario = self._random_scenario()
            if scenario.key in used:
                continue
            total, _ = hand_value(scenario.player_cards)
            if total >= 21:
                continue
            stats = self.evaluate(scenario)
            margin = abs(stats["hit"].ev - stats["stand"].ev)
            difficulty = self.difficulty(margin)
            if difficulty == "VERY_OBVIOUS":
                continue
            candidate = (scenario, stats, difficulty)
            if target is None or difficulty == target:
                return candidate
            distance = abs(target_order[difficulty] - target_order.get(target, target_order[difficulty]))
            if distance < best_distance:
                fallback, best_distance = candidate, distance
        if fallback is None:
            raise RuntimeError("Unable to generate a legal non-trivial Blackjack scenario")
        return fallback

    def generate_raw_scenario(
        self,
        used: set[tuple[str, ...]] | None = None,
        target: str | None = None,
    ) -> Scenario:
        return self.generate_scenario(target=target, used=used)[0]
