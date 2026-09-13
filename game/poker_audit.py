"""Deterministic mathematical audit fixtures for the Poker decision model.

This module is intentionally separate from the Pygame UI. Run it directly to
print benchmark equity comparisons, action EVs, uncertainty, fold matrices,
and a fully expanded aggressive-action trace.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from bisect import bisect_left
from dataclasses import dataclass, replace
from itertools import accumulate, combinations
from math import comb
import random
import time

from game.poker_equity import PokerEquityEstimator
from game.poker_ev import PokerEVModel
from game.poker_hand_evaluator import evaluate_holdem
from game.poker_models import ActionOption, Card, OpponentState, PokerAction, PokerScenario, RANK_VALUE, card_code, poker_deck
from game.poker_ranges import PokerRangeModel
from game.poker_scenarios import PokerScenarioGenerator


REFERENCE_EQUITY_SIMULATIONS = 30_000
REFERENCE_EXACT_STATE_LIMIT = 100_000


def distribution_scenarios(count: int = 240, seed: int = 913) -> tuple[PokerScenario, ...]:
    """Return a repeatable, street-balanced sample through production builders."""
    if count < 4:
        raise ValueError("Distribution audit needs at least four scenarios")
    generator = PokerScenarioGenerator(seed=seed, equity_simulations=20)
    builders = (
        generator._build_preflop,
        generator._build_flop_made_hand,
        generator._build_turn_draw,
        generator._build_turn_marginal,
        generator._build_river_bluff_catcher,
    )
    stacks = (120, 180, 260, 400, 650, 1000)
    scenarios = []
    for index in range(count):
        builder = builders[index % len(builders)]
        scenarios.append(builder(stacks[(index // len(builders)) % len(stacks)]))
    return tuple(scenarios)


def audit_preferred_distribution(
    count: int = 240,
    seed: int = 913,
    equity_simulations: int = 400,
    branch_simulations: int = 120,
) -> dict:
    """Measure preferred actions without imposing a target distribution."""
    rows = []
    for index, scenario in enumerate(distribution_scenarios(count, seed)):
        ranges = PokerRangeModel()
        equity = PokerEquityEstimator(ranges, equity_simulations, seed + index).estimate(scenario)
        evaluation = PokerEVModel(
            ranges, branch_simulations, seed + 10_000 + index, sensitivity=False
        ).evaluate(
            scenario, equity
        )
        aggressive = evaluation.best_action in {"bet", "raise"}
        candidates = (
            scenario.candidate_bet_sizes
            if evaluation.best_action == "bet"
            else scenario.candidate_raise_sizes
            if evaluation.best_action == "raise"
            else ()
        )
        largest = bool(aggressive and candidates and evaluation.best_amount == max(candidates))
        all_in = evaluation.best_key == "all_in"
        rows.append({
            "scenario": scenario,
            "equity": equity,
            "evaluation": evaluation,
            "largest": largest,
            "all_in": all_in,
            "category": _hero_category(scenario),
        })

    by_street = {}
    for street in ("preflop", "flop", "turn", "river"):
        street_rows = [row for row in rows if row["scenario"].street == street]
        denominator = len(street_rows)
        counts = Counter(row["evaluation"].best_action for row in street_rows)
        by_street[street] = {
            "count": denominator,
            "actions": {action: counts[action] / denominator for action in ("fold", "call", "check", "bet", "raise")},
            "largest": sum(row["largest"] for row in street_rows) / denominator,
            "all_in": sum(row["all_in"] for row in street_rows) / denominator,
        }

    all_ins = [row for row in rows if row["all_in"]]
    category_counts = Counter(row["category"] for row in all_ins)
    return {
        "count": len(rows),
        "by_street": by_street,
        "largest_frequency": sum(row["largest"] for row in rows) / len(rows),
        "all_in_frequency": len(all_ins) / len(rows),
        "all_in_average_effective_stack": (
            sum(row["scenario"].effective_stack for row in all_ins) / len(all_ins) if all_ins else 0.0
        ),
        "all_in_average_pot": (
            sum(row["scenario"].pot for row in all_ins) / len(all_ins) if all_ins else 0.0
        ),
        "all_in_average_effective_stack_to_pot": (
            sum(row["scenario"].effective_stack / max(1, row["scenario"].pot) for row in all_ins) / len(all_ins)
            if all_ins else 0.0
        ),
        "all_in_average_equity": (
            sum(row["equity"].equity for row in all_ins) / len(all_ins) if all_ins else 0.0
        ),
        "all_in_categories": dict(category_counts),
        "rows": rows,
    }


def print_preferred_distribution(summary: dict) -> None:
    print("\n" + "=" * 96)
    print(f"PREFERRED-ACTION DISTRIBUTION ({summary['count']} deterministic scenarios)")
    print("=" * 96)
    for street, data in summary["by_street"].items():
        actions = "  ".join(
            f"{action}={frequency:.1%}" for action, frequency in data["actions"].items() if frequency
        )
        print(
            f"{street.upper():<8} n={data['count']:<3} {actions}  "
            f"largest={data['largest']:.1%} all-in={data['all_in']:.1%}"
        )
    print(f"Largest sizing overall: {summary['largest_frequency']:.1%}")
    print(f"All-in overall:         {summary['all_in_frequency']:.1%}")
    print(f"All-in average stack:   {summary['all_in_average_effective_stack']:.1f}")
    print(f"All-in average pot:     {summary['all_in_average_pot']:.1f}")
    print(f"All-in average SPR:     {summary['all_in_average_effective_stack_to_pot']:.2f}")
    print(f"All-in average equity:  {summary['all_in_average_equity']:.1%}")
    print(f"All-in hand categories: {summary['all_in_categories']}")


def find_representative_rows(
    count: int = 240,
    seed: int = 913,
    equity_simulations: int = 1_500,
    branch_simulations: int = 350,
) -> dict[str, dict]:
    """Locate reproducible suspicious-looking cases for full explanation."""
    found: dict[str, dict] = {}
    for index, scenario in enumerate(distribution_scenarios(count, seed)):
        ranges = PokerRangeModel()
        equity = PokerEquityEstimator(ranges, equity_simulations, seed + index).estimate(scenario)
        evaluation = PokerEVModel(
            ranges, branch_simulations, seed + 10_000 + index, sensitivity=False
        ).evaluate(scenario, equity)
        row = {"name": scenario.archetype, "scenario": scenario, "ranges": ranges,
               "equity": equity, "evaluation": evaluation}
        category = _hero_category(scenario)
        if category == "one_pair" and evaluation.best_key == "all_in":
            found.setdefault("one_pair_all_in", row)
        if category in {"high_card", "offsuit"} and evaluation.best_key == "all_in":
            found.setdefault("weak_max_raise", row)
        ranks = {rank for rank, _suit in scenario.hero_cards}
        if scenario.street == "preflop" and ranks == {"A", "J"} and evaluation.best_action == "fold":
            found.setdefault("ace_jack_fold", row)
        if len(found) == 3:
            break
    return found


def _hero_category(scenario: PokerScenario) -> str:
    if scenario.street == "preflop":
        ranks = [RANK_VALUE[rank] for rank, _suit in scenario.hero_cards]
        if ranks[0] == ranks[1]:
            return "pocket_pair"
        return "suited" if scenario.hero_cards[0][1] == scenario.hero_cards[1][1] else "offsuit"
    names = ("high_card", "one_pair", "two_pair", "trips", "straight", "flush", "full_house", "quads", "straight_flush")
    return names[evaluate_holdem(scenario.hero_cards, scenario.board)[0]]


@dataclass(frozen=True)
class PokerBenchmark:
    name: str
    purpose: str
    scenario: PokerScenario


@dataclass(frozen=True)
class ReferenceEquity:
    equity: float
    win_probability: float
    tie_probability: float
    loss_probability: float
    method: str
    states: int


def card(code: str) -> Card:
    suit = {"C": "clubs", "D": "diamonds", "H": "hearts", "S": "spades"}[code[-1]]
    return code[:-1], suit


def benchmark_scenarios() -> tuple[PokerBenchmark, ...]:
    """Return twelve fixed, legal, strategically varied decision snapshots."""
    return (
        _benchmark(
            "P1 obvious preflop fold", "Obvious fold",
            "preflop", ("7C", "2D"), (), 55, 30,
            (("CO", "TIGHT", "RAISED TO 30", 30, False),
             ("SB", "BALANCED", "WAITING", 5, False),
             ("BB", "LOOSE", "WAITING", 10, False)),
        ),
        _benchmark(
            "P2 premium preflop raise", "Strong hand where raising should dominate calling",
            "preflop", ("AS", "AH"), (), 55, 30,
            (("CO", "BALANCED", "RAISED TO 30", 30, False),
             ("SB", "TIGHT", "WAITING", 5, False),
             ("BB", "LOOSE", "WAITING", 10, False)),
        ),
        _benchmark(
            "F1 top-pair value bet", "Obvious value bet",
            "flop", ("AH", "KH"), ("AD", "7C", "2S"), 100, 0,
            (("CO", "BALANCED", "CHECKED", 0, False),
             ("SB", "TIGHT", "FOLDED", 0, True),
             ("BB", "LOOSE", "FOLDED", 0, True)),
        ),
        _benchmark(
            "F2 combo draw facing bet", "Strong draw",
            "flop", ("9H", "8H"), ("7H", "6C", "2H"), 135, 35,
            (("CO", "BALANCED", "BET 35", 35, False),
             ("SB", "TIGHT", "FOLDED", 0, True),
             ("BB", "LOOSE", "FOLDED", 0, True)),
            last_full_raise=35,
        ),
        _benchmark(
            "F3 weak-air bluff", "Weak hand whose bluff depends on fold equity",
            "flop", ("QC", "JC"), ("9D", "5S", "2H"), 90, 0,
            (("CO", "TIGHT", "CHECKED", 0, False),
             ("SB", "BALANCED", "FOLDED", 0, True),
             ("BB", "LOOSE", "FOLDED", 0, True)),
        ),
        _benchmark(
            "T1 priced nut-flush draw", "Obvious call with a strong draw",
            "turn", ("AH", "JH"), ("10H", "7C", "4H", "2D"), 125, 25,
            (("CO", "LOOSE", "BET 25", 25, False),
             ("SB", "TIGHT", "FOLDED", 0, True),
             ("BB", "BALANCED", "FOLDED", 0, True)),
            last_full_raise=25,
        ),
        _benchmark(
            "T2 marginal underpair", "Marginal made hand",
            "turn", ("8S", "8D"), ("10C", "6H", "4D", "2S"), 150, 40,
            (("BB", "BALANCED", "BET 40", 40, False),
             ("SB", "TIGHT", "FOLDED", 0, True),
             ("CO", "LOOSE", "FOLDED", 0, True)),
            last_full_raise=40,
        ),
        _benchmark(
            "T3 marginal top-pair call", "Close decision",
            "turn", ("QH", "JS"), ("KC", "JD", "7H", "4S"), 155, 45,
            (("CO", "AGGRESSIVE", "BET 45", 45, False),
             ("SB", "TIGHT", "FOLDED", 0, True),
             ("BB", "BALANCED", "FOLDED", 0, True)),
            last_full_raise=45,
        ),
        _benchmark(
            "R1 one-pair bluff catcher", "Bluff catcher",
            "river", ("JH", "10H"), ("JC", "8D", "5S", "3C", "2D"), 240, 70,
            (("CO", "BALANCED", "BET 70", 70, False),
             ("SB", "TIGHT", "FOLDED", 0, True),
             ("BB", "LOOSE", "FOLDED", 0, True)),
            last_full_raise=70,
        ),
        _benchmark(
            "R2 weak river fold", "Obvious fold",
            "river", ("7C", "6C"), ("AS", "KD", "QH", "9S", "2D"), 240, 100,
            (("CO", "TIGHT", "BET 100", 100, False),
             ("SB", "BALANCED", "FOLDED", 0, True),
             ("BB", "LOOSE", "FOLDED", 0, True)),
            last_full_raise=100,
        ),
        _benchmark(
            "R3 full-house value raise", "Strong hand where raising should dominate calling",
            "river", ("AS", "AH"), ("AD", "7C", "7S", "2H", "3D"), 220, 60,
            (("CO", "LOOSE", "BET 60", 60, False),
             ("SB", "TIGHT", "FOLDED", 0, True),
             ("BB", "BALANCED", "FOLDED", 0, True)),
            last_full_raise=60,
        ),
        _benchmark(
            "M1 four-way flop stress", "Multiway made-hand stress case",
            "flop", ("KH", "QH"), ("QD", "7C", "2S"), 240, 40,
            (("SB", "TIGHT", "CHECKED", 0, False),
             ("BB", "AGGRESSIVE", "BET 40", 40, False),
             ("MP", "BALANCED", "CALLED 40", 40, False),
             ("CO", "LOOSE", "CALLED 40", 40, False)),
            last_full_raise=40,
        ),
    )


def recognizable_sanity_benchmarks() -> tuple[PokerBenchmark, ...]:
    """Recognizable preflop and postflop checks; none encode chart answers."""
    preflop = (
        _benchmark("PF AA unopened", "AA unopened", "preflop", ("AS", "AH"), (), 15, 10,
                   (("SB", "BALANCED", "POSTED 5", 5, False), ("BB", "LOOSE", "POSTED 10", 10, False), ("CO", "TIGHT", "FOLDED", 0, True))),
        _benchmark("PF KK single open", "KK versus single open", "preflop", ("KS", "KH"), (), 45, 30,
                   (("CO", "BALANCED", "RAISED TO 30", 30, False), ("SB", "TIGHT", "FOLDED", 5, True), ("BB", "LOOSE", "POSTED 10", 10, False))),
        _benchmark("PF QQ early deep", "QQ early position, deep", "preflop", ("QS", "QH"), (), 15, 10,
                   (("SB", "TIGHT", "POSTED 5", 5, False), ("BB", "BALANCED", "POSTED 10", 10, False), ("BTN", "LOOSE", "WAITING", 0, False)), hero_stack=650, hero_position="UTG"),
        _benchmark("PF AKs open caller", "AKs versus open and caller, short", "preflop", ("AS", "KS"), (), 75, 30,
                   (("MP", "BALANCED", "RAISED TO 30", 30, False), ("CO", "LOOSE", "CALLED 30", 30, False), ("BB", "TIGHT", "POSTED 10", 10, False)), hero_stack=120),
        _benchmark("PF AQs single open", "AQs versus late open", "preflop", ("AH", "QH"), (), 55, 30,
                   (("CO", "AGGRESSIVE", "RAISED TO 30", 30, False), ("SB", "TIGHT", "POSTED 5", 5, False), ("BB", "LOOSE", "POSTED 10", 10, False))),
        _benchmark("PF AJs single open", "AJs versus tight early open", "preflop", ("AH", "JH"), (), 55, 30,
                   (("UTG", "TIGHT", "RAISED TO 30", 30, False), ("SB", "BALANCED", "POSTED 5", 5, False), ("BB", "LOOSE", "POSTED 10", 10, False))),
        _benchmark("PF KQs open reraise", "KQs facing raise and re-raise", "preflop", ("KH", "QH"), (), 145, 90,
                   (("MP", "TIGHT", "RAISED TO 30", 30, False), ("CO", "BALANCED", "RAISED TO 90", 90, False), ("BB", "LOOSE", "POSTED 10", 10, False)), last_full_raise=60),
        _benchmark("PF 99 late unopened", "99 late position unopened", "preflop", ("9S", "9H"), (), 15, 10,
                   (("SB", "LOOSE", "POSTED 5", 5, False), ("BB", "BALANCED", "POSTED 10", 10, False), ("CO", "TIGHT", "FOLDED", 0, True))),
        _benchmark("PF 76s late unopened", "76s late position unopened", "preflop", ("7S", "6S"), (), 15, 10,
                   (("SB", "TIGHT", "POSTED 5", 5, False), ("BB", "BALANCED", "POSTED 10", 10, False), ("CO", "LOOSE", "FOLDED", 0, True))),
        _benchmark("PF 72o early", "weak offsuit early position", "preflop", ("7C", "2D"), (), 15, 10,
                   (("SB", "TIGHT", "POSTED 5", 5, False), ("BB", "BALANCED", "POSTED 10", 10, False), ("BTN", "LOOSE", "WAITING", 0, False)), hero_position="UTG"),
    )
    postflop_specs = (
        ("POST top pair strong", "top pair strong kicker", "flop", ("AH", "KH"), ("AD", "7C", "2S")),
        ("POST top pair weak", "top pair weak kicker", "flop", ("AH", "4H"), ("AD", "KC", "8S")),
        ("POST middle pair", "middle pair", "flop", ("9H", "8H"), ("KD", "9C", "3S")),
        ("POST overpair", "overpair", "flop", ("QH", "QS"), ("10D", "7C", "2S")),
        ("POST two pair", "two pair", "turn", ("KH", "7H"), ("KD", "7C", "2S", "4D")),
        ("POST set", "set", "turn", ("8H", "8S"), ("8D", "KC", "3S", "2H")),
        ("POST flush draw", "flush draw", "flop", ("AH", "5H"), ("KH", "8H", "2C")),
        ("POST open ended", "open-ended straight draw", "flop", ("9C", "8D"), ("7H", "6S", "KC")),
        ("POST combo draw", "combo draw", "flop", ("9H", "8H"), ("7H", "6C", "2H")),
        ("POST missed river", "missed river hand", "river", ("QH", "JH"), ("9D", "5S", "2H", "3C", "7D")),
        ("POST bluff catcher", "bluff catcher", "river", ("JH", "10H"), ("JC", "8D", "5S", "3C", "2D")),
        ("POST near nut", "near-nut hand", "river", ("AH", "KH"), ("QH", "JH", "10H", "2C", "3D")),
    )
    postflop = tuple(
        _benchmark(name, purpose, street, hero, board, 120 if street == "flop" else 220, 0,
                   (("CO", "BALANCED", "CHECKED", 0, False), ("SB", "TIGHT", "FOLDED", 0, True), ("BB", "LOOSE", "FOLDED", 0, True)))
        for name, purpose, street, hero, board in postflop_specs
    )
    return preflop + postflop


def _benchmark(
    name: str,
    purpose: str,
    street: str,
    hero_codes: tuple[str, str],
    board_codes: tuple[str, ...],
    pot: int,
    current_bet: int,
    opponent_specs: tuple[tuple[str, str, str, int, bool], ...],
    last_full_raise: int = 10,
    hero_stack: int = 300,
    hero_position: str = "BTN",
) -> PokerBenchmark:
    opponents = tuple(
        OpponentState(
            position=position,
            stack=hero_stack - contribution,
            profile=profile,
            contribution=contribution,
            folded=folded,
            status=status,
            stack_before_action=hero_stack,
        )
        for position, profile, status, contribution, folded in opponent_specs
    )
    actions = tuple(
        PokerAction(opponent.position, _status_action(opponent.status), opponent.contribution)
        for opponent in opponents
        if opponent.status != "WAITING"
    )
    scenario = PokerScenario(
        street=street,
        hero_cards=(card(hero_codes[0]), card(hero_codes[1])),
        board=tuple(card(code) for code in board_codes),
        hero_position=hero_position,
        hero_stack=hero_stack,
        hero_contribution=0,
        starting_pot=pot - sum(opponent.contribution for opponent in opponents),
        pot=pot,
        current_bet=current_bet,
        last_full_raise=last_full_raise,
        big_blind=10,
        opponents=opponents,
        action_history=actions,
        archetype=f"audit: {purpose.lower()}",
    )
    return PokerBenchmark(name, purpose, scenario)


def _status_action(status: str) -> str:
    upper = status.upper()
    if "POSTED" in upper:
        return "post"
    if "RAISED" in upper:
        return "raise"
    if "BET" in upper:
        return "bet"
    if "CALLED" in upper:
        return "call"
    if "CHECKED" in upper:
        return "check"
    return "fold"


def reference_equity(
    scenario: PokerScenario,
    range_model: PokerRangeModel,
    simulations: int = REFERENCE_EQUITY_SIMULATIONS,
    seed: int = 91,
) -> ReferenceEquity:
    """Independent exhaustive/Monte Carlo equity calculation.

    It intentionally consumes the same modeled range weights so this comparison
    isolates equity sampling and hand-ranking correctness from range quality.
    Hand evaluation and random range sampling are independently implemented.
    """
    active = scenario.active_opponents
    missing_board = 5 - len(scenario.board)
    if len(active) == 1:
        weighted = range_model.weighted_combos(scenario, active[0])
        remaining_after_hand = 52 - len(scenario.hero_cards) - len(scenario.board) - 2
        state_count = len(weighted) * comb(remaining_after_hand, missing_board)
        if state_count <= REFERENCE_EXACT_STATE_LIMIT:
            return exact_single_opponent_equity(scenario, weighted)
    return _reference_monte_carlo(scenario, range_model, simulations, seed)


def exact_single_opponent_equity(
    scenario: PokerScenario,
    weighted: tuple[tuple[tuple[Card, Card], float], ...],
) -> ReferenceEquity:
    known = set(scenario.hero_cards + scenario.board)
    missing = 5 - len(scenario.board)
    total_weight = equity_weight = win_weight = tie_weight = loss_weight = 0.0
    states = 0
    for opponent_hand, range_weight in weighted:
        blocked = known.union(opponent_hand)
        remaining = tuple(card_ for card_ in poker_deck() if card_ not in blocked)
        runouts = combinations(remaining, missing) if missing else ((),)
        runout_count = comb(len(remaining), missing)
        state_weight = range_weight / runout_count
        for runout in runouts:
            board = scenario.board + tuple(runout)
            hero_score = _reference_holdem(scenario.hero_cards, board)
            opponent_score = _reference_holdem(opponent_hand, board)
            share = 1.0 if hero_score > opponent_score else 0.5 if hero_score == opponent_score else 0.0
            total_weight += state_weight
            equity_weight += state_weight * share
            if share == 1.0:
                win_weight += state_weight
            elif share > 0:
                tie_weight += state_weight
            else:
                loss_weight += state_weight
            states += 1
    return ReferenceEquity(
        equity_weight / total_weight,
        win_weight / total_weight,
        tie_weight / total_weight,
        loss_weight / total_weight,
        "exhaustive",
        states,
    )


def _reference_monte_carlo(
    scenario: PokerScenario,
    range_model: PokerRangeModel,
    simulations: int,
    seed: int,
) -> ReferenceEquity:
    rng = random.Random(seed)
    ranges = []
    for opponent in scenario.active_opponents:
        weighted = range_model.weighted_combos(scenario, opponent)
        combos = tuple(combo for combo, _weight in weighted)
        weights = tuple(weight for _combo, weight in weighted)
        ranges.append((combos, weights, tuple(accumulate(weights))))
    known = set(scenario.hero_cards + scenario.board)
    equity_total = 0.0
    wins = ties = losses = 0
    for _ in range(simulations):
        blocked = set(known)
        hands: list[tuple[Card, Card]] = []
        for combos, weights, cumulative in ranges:
            hand: tuple[Card, Card] | None = None
            for _attempt in range(20):
                candidate = combos[bisect_left(cumulative, rng.random() * cumulative[-1])]
                if candidate[0] not in blocked and candidate[1] not in blocked:
                    hand = candidate
                    break
            if hand is None:
                legal = [(combo, weight) for combo, weight in zip(combos, weights)
                         if combo[0] not in blocked and combo[1] not in blocked]
                legal_combos, legal_weights = zip(*legal)
                legal_cumulative = tuple(accumulate(legal_weights))
                hand = legal_combos[bisect_left(legal_cumulative, rng.random() * legal_cumulative[-1])]
            assert hand is not None
            hands.append(hand)
            blocked.update(hand)
        remaining = [card_ for card_ in poker_deck() if card_ not in blocked]
        runout = tuple(rng.sample(remaining, 5 - len(scenario.board)))
        board = scenario.board + runout
        hero_score = _reference_holdem(scenario.hero_cards, board)
        opponent_scores = [_reference_holdem(hand, board) for hand in hands]
        best = max([hero_score, *opponent_scores])
        if hero_score != best:
            share = 0.0
        else:
            share = 1.0 / (1 + sum(score == hero_score for score in opponent_scores))
        equity_total += share
        if share == 1.0:
            wins += 1
        elif share > 0:
            ties += 1
        else:
            losses += 1
    return ReferenceEquity(
        equity_total / simulations,
        wins / simulations,
        ties / simulations,
        losses / simulations,
        "independent Monte Carlo",
        simulations,
    )


def _reference_holdem(hole_cards: tuple[Card, Card], board: tuple[Card, ...]) -> tuple[int, ...]:
    return max(reference_five(hand) for hand in combinations(hole_cards + board, 5))


def reference_five(cards: tuple[Card, ...]) -> tuple[int, ...]:
    values: list[int] = sorted((int(RANK_VALUE[rank]) for rank, _suit in cards), reverse=True)
    counts: Counter[int] = Counter(values)
    groups: list[tuple[int, int]] = sorted(
        ((count, value) for value, count in counts.items()), reverse=True
    )
    suits = [suit for _rank, suit in cards]
    flush = len(set(suits)) == 1
    unique = sorted(set(values), reverse=True)
    straight_high = 5 if unique == [14, 5, 4, 3, 2] else unique[0] if len(unique) == 5 and unique[0] - unique[-1] == 4 else 0
    if flush and straight_high:
        return 8, straight_high
    if groups[0][0] == 4:
        return 7, groups[0][1], groups[1][1]
    if groups[0][0] == 3 and groups[1][0] == 2:
        return 6, groups[0][1], groups[1][1]
    if flush:
        return 5, *values
    if straight_high:
        return 4, straight_high
    if groups[0][0] == 3:
        return 3, groups[0][1], *sorted((value for value in values if value != groups[0][1]), reverse=True)
    pairs: list[int] = sorted((value for value, count in counts.items() if count == 2), reverse=True)
    if len(pairs) >= 2:
        kicker = max(value for value in values if value not in pairs[:2])
        return 2, pairs[0], pairs[1], kicker
    if pairs:
        return 1, pairs[0], *sorted((value for value in values if value != pairs[0]), reverse=True)
    return 0, *values


def run_audit(
    production_simulations: int = 10_000,
    reference_simulations: int = REFERENCE_EQUITY_SIMULATIONS,
    branch_simulations: int = 1_500,
    seed: int = 41,
) -> list[dict]:
    started = time.perf_counter()
    rows = []
    print("=" * 110)
    print("POKER MATHEMATICAL BENCHMARK AUDIT")
    print("=" * 110)
    for index, benchmark in enumerate(benchmark_scenarios(), 1):
        ranges = PokerRangeModel()
        production = PokerEquityEstimator(ranges, production_simulations, seed + index).estimate(benchmark.scenario)
        reference = reference_equity(benchmark.scenario, ranges, reference_simulations, seed + 100 + index)
        evaluation = PokerEVModel(ranges, branch_simulations, seed + 200 + index).evaluate(
            benchmark.scenario, production
        )
        evs = {option.key: option.ev for option in evaluation.options}
        difference = production.equity - reference.equity
        rows.append({
            "name": benchmark.name,
            "purpose": benchmark.purpose,
            "scenario": benchmark.scenario,
            "production": production,
            "reference": reference,
            "difference": difference,
            "evaluation": evaluation,
        })
        print(
            f"{benchmark.name:<30} equity={production.equity:6.2%} "
            f"reference={reference.equity:6.2%} diff={difference:+6.2%} "
            f"legal={'/'.join(benchmark.scenario.legal_actions):<16} "
            f"best={evaluation.best_key:<14} near={','.join(evaluation.near_equivalent_keys)}"
        )
        print("  EVs: " + ", ".join(f"{key}={value:+.2f}" for key, value in evs.items()))
    print(f"\nAudit elapsed: {time.perf_counter() - started:.2f}s")
    return rows


def print_aggressive_trace(option: ActionOption) -> None:
    trace = option.aggressive_trace
    if trace is None:
        raise ValueError("Selected option is not a bet or raise")
    print("\n" + "=" * 80)
    print(f"FULL AGGRESSIVE TRACE: {option.key}")
    print(f"Pot before: {trace.pot_before}")
    print(f"Raise/bet to: {trace.raise_to}")
    print(f"Hero cost: {trace.hero_cost}")
    print(f"Pressure: {trace.pressure:.3f} pot")
    for response in trace.opponent_responses:
        print(
            f"{response.position} {response.profile} {response.prior_status}: "
            f"call_cost={response.call_cost}, pot_odds={response.pot_odds:.2%}, "
            f"fold={response.fold_probability:.2%}, "
            f"prior strength={response.prior_mean_strength:.3f}, "
            f"calling strength={response.calling_mean_strength:.3f}"
        )
    for branch in trace.branches:
        callers: str = ",".join(branch.continuing_positions) or "ALL FOLD"
        equity = "n/a" if branch.called_equity is None else f"{branch.called_equity:.2%}"
        print(
            f"callers={callers:<18} p={branch.probability:7.3%} "
            f"equity={equity:<7} final_pot={branch.final_pot:<4} "
            f"branch_ev={branch.branch_ev:+8.2f} weighted={branch.weighted_ev:+8.2f}"
        )
        if branch.called_equity is None:
            print(f"  formula: {branch.probability:.6f} * pot {branch.final_pot} = {branch.weighted_ev:+.2f}")
        else:
            print(
                f"  formula: {branch.probability:.6f} * "
                f"({branch.called_equity:.6f} * {branch.final_pot} * {trace.realization:.2f} "
                f"- {trace.hero_cost}) = {branch.weighted_ev:+.2f}"
            )
    print(f"TOTAL EV: {option.ev:+.2f} +/- {1.96 * option.standard_error:.2f} (95% MC)")
    print("=" * 80)


def evaluate_benchmarks(
    benchmarks: tuple[PokerBenchmark, ...],
    equity_simulations: int = 2_000,
    branch_simulations: int = 400,
    seed: int = 4_100,
) -> list[dict]:
    rows = []
    for index, benchmark in enumerate(benchmarks):
        ranges = PokerRangeModel()
        equity = PokerEquityEstimator(ranges, equity_simulations, seed + index).estimate(benchmark.scenario)
        evaluation = PokerEVModel(ranges, branch_simulations, seed + 1_000 + index).evaluate(
            benchmark.scenario, equity
        )
        rows.append({"name": benchmark.name, "purpose": benchmark.purpose, "scenario": benchmark.scenario,
                     "ranges": ranges, "equity": equity, "evaluation": evaluation})
    return rows


def print_benchmark_results(rows: list[dict]) -> None:
    print("\n" + "=" * 100)
    print("RECOGNIZABLE HAND SANITY REVIEW")
    print("=" * 100)
    for row in rows:
        evaluation = row["evaluation"]
        evs = ", ".join(f"{option.key}={option.ev:+.1f}" for option in evaluation.options)
        print(
            f"{row['name']:<25} equity={row['equity'].equity:6.1%} "
            f"best={evaluation.best_key:<13} sensitive={evaluation.model_sensitive} | {evs}"
        )


def print_scenario_explanation(row: dict) -> None:
    """Print enough state and arithmetic to answer why an action won."""
    scenario = row["scenario"]
    equity = row["equity"]
    evaluation = row["evaluation"]
    ranges = row.get("ranges") or PokerRangeModel()
    print("\n" + "#" * 100)
    print(f"WHY THIS ACTION: {row.get('name', scenario.archetype)}")
    print("#" * 100)
    print(f"Hero: {' '.join(card_code(value) for value in scenario.hero_cards)}")
    print(f"Board: {' '.join(card_code(value) for value in scenario.board) or '(none)'}")
    print(
        f"Street={scenario.street.upper()} position={scenario.hero_position} pot={scenario.pot} "
        f"hero_stack={scenario.hero_stack} effective_stack={scenario.effective_stack} SPR={scenario.spr:.2f}"
    )
    print("Opponents:")
    for opponent in scenario.opponents:
        print(
            f"  {opponent.position}: profile={opponent.profile} stack={opponent.stack} "
            f"contribution={opponent.contribution} status={opponent.status} folded={opponent.folded}"
        )
    print("Action history:")
    for action in scenario.action_history:
        print(f"  {action.describe()}")
    print("Modeled active ranges (top prior combos by normalized weight):")
    for opponent in scenario.active_opponents:
        weighted = ranges.weighted_combos(scenario, opponent)
        total = sum(weight for _combo, weight in weighted)
        strongest = sorted(weighted, key=lambda item: item[1], reverse=True)[:12]
        text = ", ".join(
            f"{card_code(combo[0])}{card_code(combo[1])}:{weight / total:.2%}"
            for combo, weight in strongest
        )
        print(f"  {opponent.position} ({len(weighted)} combos): {text}")
    print(
        f"Hero raw equity={equity.equity:.2%} "
        f"(win={equity.win_probability:.2%}, tie={equity.tie_probability:.2%}, "
        f"95% CI={equity.confidence_interval_95[0]:.2%}-{equity.confidence_interval_95[1]:.2%})"
    )
    print(f"Legal actions: {', '.join(scenario.legal_actions)}")
    print(f"Bet candidates: {scenario.candidate_bet_sizes}; player-facing: {scenario.player_candidate_bet_sizes}")
    print(f"Raise candidates: {scenario.candidate_raise_sizes}; player-facing: {scenario.player_candidate_raise_sizes}")
    for option in evaluation.options:
        print(f"\nOPTION {option.key}: EV={option.ev:+.3f} +/- {1.96 * option.standard_error:.3f}")
        if option.aggressive_trace is not None:
            print_aggressive_trace(option)
    print(
        f"RESULT: {evaluation.best_key}; near={evaluation.near_equivalent_keys}; "
        f"sensitivity winners={evaluation.sensitivity_best_keys}; model_sensitive={evaluation.model_sensitive}"
    )


def fold_probability_matrix() -> tuple[dict, ...]:
    """Audit profile/street/status/pressure fold behavior after conditioning."""
    bases = {
        "flop": benchmark_scenarios()[4].scenario,
        "turn": benchmark_scenarios()[7].scenario,
        "river": benchmark_scenarios()[8].scenario,
    }
    rows = []
    for street, base in bases.items():
        for profile in ("TIGHT", "BALANCED", "LOOSE", "AGGRESSIVE"):
            for status in ("CHECKED", "CALLED 40", "BET 40", "RAISED TO 80"):
                original = base.active_opponents[0]
                opponent = replace(original, profile=profile, status=status, stack=300, contribution=0)
                scenario = replace(base, pot=100, opponents=(opponent,) + tuple(base.opponents[1:]))
                model = PokerEVModel(PokerRangeModel(), branch_simulations=20, seed=3)
                probabilities = []
                for label, cost in (("small", 25), ("medium", 50), ("large", 100), ("all_in", 300)):
                    conditioned = model.range_model.conditional_calling_range(
                        scenario, opponent, cost
                    )
                    probabilities.append((label, conditioned.fold_probability))
                rows.append({
                    "street": street,
                    "profile": profile,
                    "status": status,
                    "probabilities": tuple(probabilities),
                })
    return tuple(rows)


def print_fold_probability_matrix() -> None:
    print("\n" + "=" * 96)
    print("FOLD-PROBABILITY MATRIX (range-conditioned aggregate fold rate)")
    print("=" * 96)
    for row in fold_probability_matrix():
        values = "  ".join(
            f"{label}={probability:5.1%}" for label, probability in row["probabilities"]
        )
        print(f"{row['street']:<6} {row['profile']:<10} {row['status']:<13} {values}")


def print_all_aggressive_traces(rows: list[dict]) -> None:
    """Print the complete reason for every benchmark bet/raise candidate."""
    for row in rows:
        print(f"\n### {row['name']} — {row['purpose']}")
        for option in row["evaluation"].options:
            if option.aggressive_trace is not None:
                print_aggressive_trace(option)


if __name__ == "__main__":
    audit_rows = run_audit()
    print_all_aggressive_traces(audit_rows)
    print_fold_probability_matrix()
