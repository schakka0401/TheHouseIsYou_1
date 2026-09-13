"""Dependency-free Texas Hold'em hand ranking and showdown comparison."""
from __future__ import annotations

from collections import Counter
from game.poker_models import Card, RANK_VALUE


HAND_NAMES = {
    8: "straight flush",
    7: "four of a kind",
    6: "full house",
    5: "flush",
    4: "straight",
    3: "three of a kind",
    2: "two pair",
    1: "pair",
    0: "high card",
}

HandScore = tuple[int, ...]


def evaluate_five(cards: tuple[Card, ...] | list[Card]) -> HandScore:
    """Return a lexicographically comparable score for exactly five cards."""
    if len(cards) != 5:
        raise ValueError("A five-card evaluator requires exactly five cards")
    if len(set(cards)) != 5:
        raise ValueError("A poker hand cannot contain duplicate cards")

    values = sorted((RANK_VALUE[rank] for rank, _suit in cards), reverse=True)
    suits = [suit for _rank, suit in cards]
    counts = Counter(values)
    grouped = sorted(counts.items(), key=lambda item: (item[1], item[0]), reverse=True)
    flush = len(set(suits)) == 1
    straight_high = _straight_high(values)

    if flush and straight_high:
        return (8, straight_high)
    if grouped[0][1] == 4:
        quad = grouped[0][0]
        kicker = max(value for value in values if value != quad)
        return (7, quad, kicker)
    trips = sorted((value for value, count in counts.items() if count == 3), reverse=True)
    pairs = sorted((value for value, count in counts.items() if count == 2), reverse=True)
    if trips and pairs:
        return (6, trips[0], pairs[0])
    if flush:
        return (5, *values)
    if straight_high:
        return (4, straight_high)
    if trips:
        kickers = sorted((value for value in values if value != trips[0]), reverse=True)[:2]
        return (3, trips[0], *kickers)
    if len(pairs) >= 2:
        high_pair, low_pair = pairs[:2]
        kicker = max(value for value in values if value not in (high_pair, low_pair))
        return (2, high_pair, low_pair, kicker)
    if pairs:
        kickers = sorted((value for value in values if value != pairs[0]), reverse=True)[:3]
        return (1, pairs[0], *kickers)
    return (0, *values)


def evaluate_holdem(hole_cards: tuple[Card, Card], board: tuple[Card, ...]) -> HandScore:
    """Evaluate the best five-card hand available from Hold'em hole cards and board."""
    cards = tuple(hole_cards) + tuple(board)
    if len(cards) < 5 or len(cards) > 7:
        raise ValueError("Hold'em evaluation requires five to seven total cards")
    if len(cards) != len(set(cards)):
        raise ValueError("Hold'em cards must be unique")
    values = [RANK_VALUE[rank] for rank, _suit in cards]
    counts = Counter(values)
    by_suit: dict[str, list[int]] = {}
    for (rank, suit) in cards:
        by_suit.setdefault(suit, []).append(RANK_VALUE[rank])

    straight_flushes = [_straight_high(suited) for suited in by_suit.values() if len(suited) >= 5]
    straight_flush_high = max(straight_flushes, default=0)
    if straight_flush_high:
        return (8, straight_flush_high)

    quads = sorted((value for value, count in counts.items() if count == 4), reverse=True)
    if quads:
        kicker = max(value for value in values if value != quads[0])
        return (7, quads[0], kicker)

    trips = sorted((value for value, count in counts.items() if count >= 3), reverse=True)
    pair_values = sorted((value for value, count in counts.items() if count >= 2), reverse=True)
    if trips:
        full_house_pairs = [value for value in pair_values if value != trips[0]]
        if full_house_pairs:
            return (6, trips[0], full_house_pairs[0])

    flushes = [sorted(suited, reverse=True)[:5] for suited in by_suit.values() if len(suited) >= 5]
    if flushes:
        return (5, *max(flushes))

    straight_high = _straight_high(values)
    if straight_high:
        return (4, straight_high)
    if trips:
        kickers = sorted((value for value in values if value != trips[0]), reverse=True)[:2]
        return (3, trips[0], *kickers)
    if len(pair_values) >= 2:
        high_pair, low_pair = pair_values[:2]
        kicker = max(value for value in values if value not in (high_pair, low_pair))
        return (2, high_pair, low_pair, kicker)
    if pair_values:
        kickers = sorted((value for value in values if value != pair_values[0]), reverse=True)[:3]
        return (1, pair_values[0], *kickers)
    return (0, *sorted(values, reverse=True)[:5])


def showdown_share(hero_score: HandScore, opponent_scores: list[HandScore]) -> float:
    """Return Hero's pot share, splitting exactly among tied winners."""
    best = max([hero_score, *opponent_scores])
    if hero_score != best:
        return 0.0
    winners = 1 + sum(score == best for score in opponent_scores)
    return 1.0 / winners


def _straight_high(values: list[int]) -> int:
    unique = set(values)
    if 14 in unique:
        unique.add(1)
    ordered = sorted(unique)
    run = 1
    best = 0
    for previous, current in zip(ordered, ordered[1:]):
        if current == previous + 1:
            run += 1
            if run >= 5:
                best = current
        elif current != previous:
            run = 1
    return best
