"""Blackjack scenario generation and Monte Carlo decision evaluation.

Rules are intentionally limited to HIT/STAND: the dealer hits below 17 and
stands on every 17, aces are soft 11/1, face cards are worth 10, and there is
no split, double, surrender, insurance, or blackjack payout special case.
Visible cards are removed from every simulation deck.
"""
from __future__ import annotations

from dataclasses import dataclass
import random

Card = tuple[str, str]
RANKS = ("2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A")
SUITS = ("clubs", "diamonds", "hearts", "spades")
SIMULATIONS_PER_ACTION = 50_000
EASY_MARGIN = 0.20
MEDIUM_MARGIN = 0.08


@dataclass(frozen=True)
class Scenario:
    player_cards: tuple[Card, Card]
    dealer_upcard: Card

    @property
    def key(self):
        # Suits do not change strategy. Rank/softness state is the cache key,
        # while the original cards remain available for exact deck removal.
        player_ranks = tuple(sorted(rank for rank, _ in self.player_cards))
        return player_ranks + (self.dealer_upcard[0],)


@dataclass
class SimulationStats:
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


def hand_value(cards: list[Card]) -> tuple[int, bool]:
    total = sum(card_value(rank) for rank, _ in cards)
    aces = sum(rank == "A" for rank, _ in cards)
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total, aces > 0


def continuation_action(cards: list[Card], dealer_upcard: Card) -> str:
    """Small fixed basic-strategy policy used only after an initial HIT."""
    total, soft = hand_value(cards)
    dealer = card_value(dealer_upcard[0])
    if soft:
        if total >= 19:
            return "stand"
        if total == 18 and dealer in {2, 7, 8}:
            return "stand"
        return "hit"
    if total >= 17:
        return "stand"
    if total >= 13 and dealer <= 6:
        return "stand"
    if total == 12 and dealer in {4, 5, 6}:
        return "stand"
    return "hit"


class BlackjackEngine:
    """Evaluates exact visible blackjack states without blocking render frames."""

    def __init__(self, seed: int | None = None, simulations: int = SIMULATIONS_PER_ACTION):
        self.random = random.Random(seed)
        self.simulations = simulations
        self.cache: dict[tuple, dict[str, SimulationStats]] = {}

    @staticmethod
    def deck() -> list[Card]:
        return [(rank, suit) for rank in RANKS for suit in SUITS]

    @staticmethod
    def difficulty(margin: float) -> str:
        if margin >= EASY_MARGIN:
            return "EASY"
        if margin >= MEDIUM_MARGIN:
            return "MEDIUM"
        return "HARD"

    def _draw(self, deck: list[Card]) -> Card:
        return deck.pop(self.random.randrange(len(deck)))

    def _dealer_total(self, dealer_cards: list[Card], deck: list[Card]) -> int:
        while hand_value(dealer_cards)[0] < 17:
            dealer_cards.append(self._draw(deck))
        return hand_value(dealer_cards)[0]

    def _finish(self, player_total: int, dealer_upcard: Card, deck: list[Card], player_cards: list[Card]) -> str:
        if player_total > 21:
            return "loss"
        dealer_cards = [dealer_upcard, self._draw(deck)]
        dealer_total = self._dealer_total(dealer_cards, deck)
        if dealer_total > 21 or player_total > dealer_total:
            return "win"
        if player_total < dealer_total:
            return "loss"
        return "push"

    def _simulate_action(self, scenario: Scenario, action: str) -> SimulationStats:
        counts = {"win": 0, "loss": 0, "push": 0}
        visible = list(scenario.player_cards) + [scenario.dealer_upcard]
        for _ in range(self.simulations):
            deck = [card for card in self.deck() if card not in visible]
            player_cards = list(scenario.player_cards)
            if action == "hit":
                player_cards.append(self._draw(deck))
                while hand_value(player_cards)[0] <= 21 and continuation_action(player_cards, scenario.dealer_upcard) == "hit":
                    player_cards.append(self._draw(deck))
            total, _ = hand_value(player_cards)
            counts[self._finish(total, scenario.dealer_upcard, deck, player_cards)] += 1
        n = float(self.simulations)
        return SimulationStats(counts["win"] / n, counts["loss"] / n, counts["push"] / n)

    def evaluate(self, scenario: Scenario) -> dict[str, SimulationStats]:
        if scenario.key not in self.cache:
            self.cache[scenario.key] = {
                "hit": self._simulate_action(scenario, "hit"),
                "stand": self._simulate_action(scenario, "stand"),
            }
        return self.cache[scenario.key]

    def resolve(self, scenario: Scenario, action: str) -> str:
        """Run one real random completion after the decision is locked."""
        visible = list(scenario.player_cards) + [scenario.dealer_upcard]
        deck = [card for card in self.deck() if card not in visible]
        player_cards = list(scenario.player_cards)
        if action == "hit":
            player_cards.append(self._draw(deck))
            while hand_value(player_cards)[0] <= 21 and continuation_action(player_cards, scenario.dealer_upcard) == "hit":
                player_cards.append(self._draw(deck))
        total, _ = hand_value(player_cards)
        return self._finish(total, scenario.dealer_upcard, deck, player_cards)

    def generate_scenario(self, target: str | None = None, used: set[tuple] | None = None) -> tuple[Scenario, dict[str, SimulationStats], str]:
        used = used or set()
        fallback = None
        for _ in range(500):
            cards = self.deck()
            player_cards = (self._draw(cards), self._draw(cards))
            dealer_upcard = self._draw(cards)
            scenario = Scenario(player_cards, dealer_upcard)
            if scenario.key in used:
                continue
            total, _ = hand_value(list(player_cards))
            if total > 21:
                continue
            stats = self.evaluate(scenario)
            margin = abs(stats["hit"].ev - stats["stand"].ev)
            difficulty = self.difficulty(margin)
            fallback = (scenario, stats, difficulty)
            if target is None or difficulty == target:
                return fallback
        if fallback is None:
            raise RuntimeError("Unable to generate a blackjack scenario")
        return fallback

    def generate_raw_scenario(self, used: set[tuple] | None = None) -> Scenario:
        """Generate a gameplay scenario without any EV/Monte Carlo work."""
        used = used or set()
        for _ in range(500):
            cards = self.deck()
            scenario = Scenario((self._draw(cards), self._draw(cards)), self._draw(cards))
            if scenario.key in used:
                continue
            total, _ = hand_value(list(scenario.player_cards))
            if total <= 21:
                return scenario
        raise RuntimeError("Unable to generate a unique blackjack scenario")
