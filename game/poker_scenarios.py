"""Intentional legal Hold'em snapshot generation for five-round sessions."""
from __future__ import annotations

import random
import time

from game.poker_betting import PokerActionHistory
from game.poker_equity import EQUITY_SIMULATIONS, PokerEquityEstimator
from game.poker_ev import PokerEVModel
from game.poker_models import Card, OpponentState, PokerScenario, PreparedPokerRound
from game.poker_ranges import PROFILES, PokerRangeModel


POKER_ROUNDS = 5
VERY_OBVIOUS_EV_MARGIN = 0.45  # normalized by the pot

ARCHETYPES = (
    "preflop",
    "flop_made_hand",
    "turn_draw",
    "turn_marginal",
    "river_bluff_catcher",
)


class PokerScenarioGenerator:
    """Generate one audited archetype per round and evaluate it exactly once."""

    def __init__(self, seed: int | None = None, equity_simulations: int = EQUITY_SIMULATIONS) -> None:
        self.random = random.Random(seed)
        self.range_model = PokerRangeModel()
        self.equity_estimator = PokerEquityEstimator(
            self.range_model,
            simulations=equity_simulations,
            seed=seed,
        )
        self.ev_model = PokerEVModel(
            self.range_model,
            branch_simulations=min(1_500, equity_simulations),
            seed=seed,
        )

    def generate_round(self, round_index: int, hero_stack: int) -> PreparedPokerRound:
        if not 1 <= round_index <= POKER_ROUNDS:
            raise ValueError(f"Poker round index must be 1-{POKER_ROUNDS}")
        if hero_stack <= 0:
            raise ValueError("Hero needs chips to receive a Poker scenario")
        started = time.perf_counter()
        archetype = ARCHETYPES[round_index - 1]
        smallest_margin = float("inf")
        for _attempt in range(8):
            scenario = getattr(self, f"_build_{archetype}")(hero_stack)
            equity = self.equity_estimator.estimate(scenario)
            evaluation = self.ev_model.evaluate(scenario, equity)
            normalized_margin = evaluation.decision_margin / max(1, scenario.pot)
            smallest_margin = min(smallest_margin, normalized_margin)
            if normalized_margin < VERY_OBVIOUS_EV_MARGIN:
                return PreparedPokerRound(
                    scenario=scenario,
                    equity=equity,
                    evaluation=evaluation,
                    generation_seconds=time.perf_counter() - started,
                )
        raise ValueError(
            f"Could not generate a non-trivial {archetype} scenario after 8 attempts; "
            f"smallest normalized EV margin was {smallest_margin:.3f}"
        )

    def _build_preflop(self, hero_stack: int) -> PokerScenario:
        hero_cards = self.random.choice((
            (_card("AS"), _card("QS")),
            (_card("9H"), _card("9C")),
            (_card("KD"), _card("QD")),
            (_card("AC"), _card("JH")),
        ))
        positions = ("UTG", "MP", "CO", "BTN", "SB", "BB")
        actions = (
            ("post", "SB", 5),
            ("post", "BB", 10),
            ("act", "UTG", "fold", 0),
            ("act", "MP", "call", 10),
            ("act", "CO", "raise", 30),
        )
        return self._assemble(
            street="preflop",
            hero_cards=hero_cards,
            board=(),
            hero_position="BTN",
            hero_stack=hero_stack,
            positions=positions,
            starting_pot=0,
            actions=actions,
            archetype="preflop range versus cutoff open",
        )

    def _build_flop_made_hand(self, hero_stack: int) -> PokerScenario:
        hero_cards, board = self.random.choice((
            ((_card("KH"), _card("QH")), (_card("QD"), _card("7C"), _card("2S"))),
            ((_card("AD"), _card("9D")), (_card("AS"), _card("8C"), _card("5H"))),
            ((_card("JC"), _card("10C")), (_card("10H"), _card("6D"), _card("3S"))),
        ))
        positions = ("SB", "BB", "CO", "BTN")
        actions = (
            ("act", "SB", "check", 0),
            ("act", "BB", "check", 0),
            ("act", "CO", "check", 0),
        )
        return self._assemble(
            street="flop",
            hero_cards=hero_cards,
            board=board,
            hero_position="BTN",
            hero_stack=hero_stack,
            positions=positions,
            starting_pot=self.random.choice((70, 80, 90)),
            actions=actions,
            archetype="flop made hand checked to hero",
        )

    def _build_turn_draw(self, hero_stack: int) -> PokerScenario:
        hero_cards, board = self.random.choice((
            ((_card("AS"), _card("JS")), (_card("10S"), _card("7C"), _card("4S"), _card("2D"))),
            ((_card("9H"), _card("8H")), (_card("7H"), _card("6C"), _card("2H"), _card("KD"))),
            ((_card("QC"), _card("JC")), (_card("10D"), _card("8C"), _card("3C"), _card("2S"))),
        ))
        positions = ("SB", "BB", "CO", "BTN")
        bet = self.random.choice((45, 50, 60))
        actions = (
            ("act", "SB", "check", 0),
            ("act", "BB", "bet", bet),
            ("act", "CO", "fold", 0),
        )
        return self._assemble(
            street="turn",
            hero_cards=hero_cards,
            board=board,
            hero_position="BTN",
            hero_stack=hero_stack,
            positions=positions,
            starting_pot=self.random.choice((100, 110, 120)),
            actions=actions,
            archetype="turn draw facing a bet",
        )

    def _build_turn_marginal(self, hero_stack: int) -> PokerScenario:
        hero_cards, board = self.random.choice((
            ((_card("9C"), _card("9D")), (_card("JH"), _card("7S"), _card("3D"), _card("2C"))),
            ((_card("QH"), _card("JS")), (_card("KC"), _card("JD"), _card("7H"), _card("4S"))),
            ((_card("8S"), _card("8D")), (_card("10C"), _card("6H"), _card("4D"), _card("2S"))),
        ))
        positions = ("SB", "BB", "CO", "BTN")
        bet = self.random.choice((35, 40, 45))
        actions = (
            ("act", "SB", "check", 0),
            ("act", "BB", "bet", bet),
        )
        return self._assemble(
            street="turn",
            hero_cards=hero_cards,
            board=board,
            hero_position="CO",
            hero_stack=hero_stack,
            positions=positions,
            starting_pot=self.random.choice((90, 100, 110)),
            actions=actions,
            archetype="marginal turn hand with a player behind",
        )

    def _build_river_bluff_catcher(self, hero_stack: int) -> PokerScenario:
        hero_cards, board = self.random.choice((
            ((_card("AS"), _card("QD")), (_card("AC"), _card("8H"), _card("7S"), _card("4C"), _card("2D"))),
            ((_card("KS"), _card("QH")), (_card("KD"), _card("9C"), _card("6S"), _card("2H"), _card("3D"))),
            ((_card("JH"), _card("10H")), (_card("JC"), _card("8D"), _card("5S"), _card("3C"), _card("2D"))),
        ))
        positions = ("SB", "BB", "CO", "BTN")
        bet = self.random.choice((50, 60, 70))
        actions = (
            ("act", "SB", "check", 0),
            ("act", "BB", "check", 0),
            ("act", "CO", "bet", bet),
        )
        return self._assemble(
            street="river",
            hero_cards=hero_cards,
            board=board,
            hero_position="BTN",
            hero_stack=hero_stack,
            positions=positions,
            starting_pot=self.random.choice((150, 170, 190)),
            actions=actions,
            archetype="river bluff catcher facing a polarized bet",
        )

    def _assemble(
        self,
        *,
        street: str,
        hero_cards: tuple[Card, Card],
        board: tuple[Card, ...],
        hero_position: str,
        hero_stack: int,
        positions: tuple[str, ...],
        starting_pot: int,
        actions: tuple[tuple, ...],
        archetype: str,
    ) -> PokerScenario:
        stacks = {position: self._opponent_stack(hero_stack) for position in positions}
        stacks[hero_position] = hero_stack
        history = PokerActionHistory(positions, stacks, starting_pot, big_blind=10)
        for instruction in actions:
            if instruction[0] == "post":
                _kind, actor, amount = instruction
                history.post(actor, amount)
            else:
                _kind, actor, action, amount = instruction
                history.act(actor, action, amount)
        if history.next_actor != hero_position:
            raise ValueError(f"Generated action history does not reach Hero: next is {history.next_actor}")

        profiles = self._profiles_for(positions)
        opponents = tuple(
            OpponentState(
                position=position,
                stack=history.seats[position].stack,
                profile=profiles[position],
                contribution=history.seats[position].contribution,
                folded=history.seats[position].folded,
                status=history.seats[position].status,
                stack_before_action=history.seats[position].stack + history.seats[position].contribution,
            )
            for position in positions
            if position != hero_position
        )
        hero_seat = history.seats[hero_position]
        return PokerScenario(
            street=street,
            hero_cards=hero_cards,
            board=board,
            hero_position=hero_position,
            hero_stack=hero_seat.stack,
            hero_contribution=hero_seat.contribution,
            starting_pot=starting_pot,
            pot=history.pot,
            current_bet=history.current_bet,
            last_full_raise=history.last_full_raise,
            big_blind=history.big_blind,
            opponents=opponents,
            action_history=tuple(history.actions),
            archetype=archetype,
        )

    def _opponent_stack(self, hero_stack: int) -> int:
        baseline = max(160, hero_stack)
        return max(120, min(1500, round(baseline * self.random.uniform(0.72, 1.35))))

    def _profiles_for(self, positions: tuple[str, ...]) -> dict[str, str]:
        shuffled = list(PROFILES)
        self.random.shuffle(shuffled)
        return {position: shuffled[index % len(shuffled)] for index, position in enumerate(positions)}


def _card(code: str) -> Card:
    suit = {"C": "clubs", "D": "diamonds", "H": "hearts", "S": "spades"}[code[-1]]
    rank = code[:-1]
    return rank, suit
