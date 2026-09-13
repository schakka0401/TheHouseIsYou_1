"""Core immutable data structures for the Poker decision experiment."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypeAlias


Card: TypeAlias = tuple[str, str]

RANKS = ("2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A")
SUITS = ("clubs", "diamonds", "hearts", "spades")
RANK_VALUE = {rank: value for value, rank in enumerate(RANKS, start=2)}
STREET_BOARD_COUNTS = {"preflop": 0, "flop": 3, "turn": 4, "river": 5}


def poker_deck() -> tuple[Card, ...]:
    return tuple((rank, suit) for suit in SUITS for rank in RANKS)


def card_code(card: Card) -> str:
    rank, suit = card
    symbol = {"clubs": "C", "diamonds": "D", "hearts": "H", "spades": "S"}[suit]
    return f"{rank}{symbol}"


@dataclass(frozen=True)
class PokerAction:
    actor: str
    action: str
    amount: int = 0

    def describe(self) -> str:
        action = self.action.upper()
        if self.action == "post":
            return f"{self.actor} posts {self.amount}"
        if self.action in {"bet", "raise", "call"}:
            connector = "to" if self.action in {"bet", "raise"} else ""
            return f"{self.actor} {action} {connector} {self.amount}".replace("  ", " ")
        return f"{self.actor} {action}"


@dataclass(frozen=True)
class OpponentState:
    position: str
    stack: int
    profile: str
    contribution: int = 0
    folded: bool = False
    status: str = "WAITING"
    stack_before_action: int | None = None


@dataclass(frozen=True)
class PokerScenario:
    street: str
    hero_cards: tuple[Card, Card]
    board: tuple[Card, ...]
    hero_position: str
    hero_stack: int
    hero_contribution: int
    starting_pot: int
    pot: int
    current_bet: int
    last_full_raise: int
    big_blind: int
    opponents: tuple[OpponentState, ...]
    action_history: tuple[PokerAction, ...]
    archetype: str

    def __post_init__(self) -> None:
        if self.street not in STREET_BOARD_COUNTS:
            raise ValueError(f"Unknown Hold'em street: {self.street}")
        if len(self.board) != STREET_BOARD_COUNTS[self.street]:
            raise ValueError(f"{self.street} requires {STREET_BOARD_COUNTS[self.street]} board cards")
        known = self.hero_cards + self.board
        if len(known) != len(set(known)):
            raise ValueError("Poker scenario contains duplicate known cards")
        if any(card not in poker_deck() for card in known):
            raise ValueError("Poker scenario contains an invalid card")
        if self.hero_stack < 0 or self.pot < 0 or self.current_bet < 0:
            raise ValueError("Stacks, pot, and current bet must be non-negative")
        if self.hero_contribution < 0 or self.hero_contribution > self.current_bet:
            raise ValueError("Hero contribution cannot exceed the live bet")
        if not 3 <= len(self.opponents) <= 6:
            raise ValueError("A scenario must begin with 3 to 6 opponents")
        if not 1 <= len(self.active_opponents) <= 4:
            raise ValueError("A scenario must retain 1 to 4 active/relevant opponents")

    @property
    def amount_to_call(self) -> int:
        return min(self.hero_stack, max(0, self.current_bet - self.hero_contribution))

    @property
    def minimum_raise_to(self) -> int:
        if self.current_bet == 0:
            return max(self.big_blind, 1)
        return self.current_bet + max(self.last_full_raise, self.big_blind)

    @property
    def active_opponents(self) -> tuple[OpponentState, ...]:
        return tuple(opponent for opponent in self.opponents if not opponent.folded)

    @property
    def effective_stack(self) -> int:
        deepest_relevant = max(
            (opponent.stack + opponent.contribution for opponent in self.active_opponents),
            default=self.hero_stack,
        )
        return min(self.hero_stack + self.hero_contribution, deepest_relevant)

    @property
    def spr(self) -> float:
        return self.effective_stack / max(1, self.pot)

    @property
    def legal_actions(self) -> tuple[str, ...]:
        if self.amount_to_call > 0:
            actions = ["fold"]
            if self.hero_stack > 0:
                actions.append("call")
            if self.hero_contribution + self.hero_stack > self.current_bet:
                actions.append("raise")
            return tuple(actions)
        actions = ["check"]
        if self.hero_stack > 0 and self.active_opponents:
            actions.append("bet")
        return tuple(actions)

    @property
    def candidate_bet_sizes(self) -> tuple[int, ...]:
        if "bet" not in self.legal_actions:
            return ()
        maximum = self.effective_stack
        raw = (
            round(self.pot * 0.50),
            round(self.pot * 0.75),
            round(self.pot),
            round(self.pot * 1.25),
            round(self.pot * 1.50),
            maximum,
        )
        return _legal_unique_sizes(raw, self.minimum_raise_to, maximum)

    @property
    def player_candidate_bet_sizes(self) -> tuple[int, ...]:
        return self._player_facing_sizes(self.candidate_bet_sizes)

    @property
    def candidate_raise_sizes(self) -> tuple[int, ...]:
        if "raise" not in self.legal_actions:
            return ()
        maximum = self.effective_stack
        raw = (
            round(self.current_bet * 2.5),
            round(self.current_bet * 3.0),
            round(self.current_bet * 4.0),
            maximum,
        )
        # A short all-in raise is legal even when it does not constitute a full raise.
        full_raises = _legal_unique_sizes(raw, self.minimum_raise_to, maximum)
        if self.current_bet < maximum < self.minimum_raise_to:
            return (maximum,)
        return full_raises

    @property
    def player_candidate_raise_sizes(self) -> tuple[int, ...]:
        return self._player_facing_sizes(self.candidate_raise_sizes)

    def _player_facing_sizes(self, sizes: tuple[int, ...]) -> tuple[int, ...]:
        """Hide only implausibly huge deep-stack shoves; backend EV keeps them."""
        maximum = self.effective_stack
        if maximum not in sizes:
            return sizes
        shove_cost = max(0, maximum - self.hero_contribution)
        plausible = self.spr <= 2.0 or shove_cost <= 1.5 * max(1, self.pot)
        filtered = sizes if plausible else tuple(amount for amount in sizes if amount != maximum)
        return filtered or (maximum,)

    @property
    def key(self) -> tuple:
        return (
            self.street,
            self.hero_cards,
            self.board,
            self.hero_position,
            self.hero_stack,
            self.pot,
            self.current_bet,
            tuple((o.position, o.stack, o.profile, o.contribution, o.folded, o.status) for o in self.opponents),
        )


def _legal_unique_sizes(raw_sizes: tuple[int, ...], minimum: int, maximum: int) -> tuple[int, ...]:
    if maximum < minimum:
        return ()
    return tuple(sorted({max(minimum, min(maximum, amount)) for amount in raw_sizes if amount > 0}))


@dataclass(frozen=True)
class EquityResult:
    equity: float
    win_probability: float
    tie_probability: float
    loss_probability: float
    simulations: int
    standard_error: float = 0.0

    @property
    def confidence_interval_95(self) -> tuple[float, float]:
        radius = 1.96 * self.standard_error
        return max(0.0, self.equity - radius), min(1.0, self.equity + radius)


@dataclass(frozen=True)
class OpponentResponse:
    position: str
    profile: str
    prior_status: str
    fold_probability: float
    prior_mean_strength: float
    calling_mean_strength: float
    pot_odds: float = 0.0
    call_cost: int = 0


@dataclass(frozen=True)
class AggressiveBranch:
    continuing_positions: tuple[str, ...]
    probability: float
    called_equity: float | None
    called_equity_standard_error: float
    final_pot: int
    branch_ev: float
    weighted_ev: float


@dataclass(frozen=True)
class AggressiveActionTrace:
    raise_to: int
    pot_before: int
    hero_cost: int
    pressure: float
    realization: float
    simulations_per_called_branch: int
    opponent_responses: tuple[OpponentResponse, ...]
    branches: tuple[AggressiveBranch, ...]


@dataclass(frozen=True)
class ActionOption:
    key: str
    action: str
    amount: int | None
    ev: float
    standard_error: float = 0.0
    aggressive_trace: AggressiveActionTrace | None = None


@dataclass(frozen=True)
class PokerActionEvaluation:
    options: tuple[ActionOption, ...]
    best_key: str
    best_action: str
    best_amount: int | None
    preferred_size_range: tuple[int, int] | None
    best_ev: float
    decision_margin: float
    difficulty: str
    near_equivalent_keys: tuple[str, ...] = ()
    sensitivity_best_keys: tuple[str, ...] = ()
    model_sensitive: bool = False
    oversized_shove_review: bool = False

    @property
    def action_evs(self) -> dict[str, float]:
        return {option.key: option.ev for option in self.options}

    def option_for(self, action: str, amount: int | None = None) -> ActionOption:
        candidates = [option for option in self.options if option.action == action]
        if not candidates:
            raise ValueError(f"Action is not legal in this scenario: {action}")
        if amount is None:
            exact = [option for option in candidates if option.amount is None]
            if exact:
                return exact[0]
            return max(candidates, key=lambda option: option.ev)
        exact = [option for option in candidates if option.amount == amount]
        if not exact:
            raise ValueError(f"Amount was not one of the modeled candidates: {amount}")
        return exact[0]


@dataclass
class PokerDecisionRecord:
    round_number: int
    scenario: PokerScenario
    equity: EquityResult
    evaluation: PokerActionEvaluation
    final_action_history: tuple[PokerAction, ...]
    player_action: str
    player_amount: int | None
    confidence_percent: int
    confidence_probability: float
    chosen_ev: float
    best_ev: float
    ev_regret: float
    exact_preferred: bool
    acceptable_action: bool
    action_family_preferred: bool
    sizing_acceptable: bool
    decision_classification: str
    # Compatibility name: "correct" means model-preferred or near-equivalent.
    action_correct: bool
    sizing_regret: float

    def as_dict(self) -> dict:
        scenario = self.scenario
        return {
            "round": self.round_number,
            "street": scenario.street,
            "hero_cards": list(scenario.hero_cards),
            "board": list(scenario.board),
            "hero_position": scenario.hero_position,
            "hero_stack": scenario.hero_stack,
            "pot": scenario.pot,
            "current_bet": scenario.current_bet,
            "amount_to_call": scenario.amount_to_call,
            "opponents": [opponent.__dict__.copy() for opponent in scenario.opponents],
            "action_history": [action.__dict__.copy() for action in self.final_action_history],
            "hero_equity": self.equity.equity,
            "win_probability": self.equity.win_probability,
            "tie_probability": self.equity.tie_probability,
            "legal_actions": list(scenario.legal_actions),
            "player_action": self.player_action,
            "player_amount": self.player_amount,
            "confidence_percent": self.confidence_percent,
            "confidence_probability": self.confidence_probability,
            "action_evs": self.evaluation.action_evs,
            "action_standard_errors": {
                option.key: option.standard_error for option in self.evaluation.options
            },
            "best_action": self.evaluation.best_action,
            "best_amount": self.evaluation.best_amount,
            "preferred_size_range": self.evaluation.preferred_size_range,
            "chosen_ev": self.chosen_ev,
            "best_ev": self.best_ev,
            "ev_regret": self.ev_regret,
            "exact_preferred": self.exact_preferred,
            "acceptable_action": self.acceptable_action,
            "action_family_preferred": self.action_family_preferred,
            "sizing_acceptable": self.sizing_acceptable,
            "sizing_regret": self.sizing_regret,
            "decision_classification": self.decision_classification,
            "decision_margin": self.evaluation.decision_margin,
            "difficulty": self.evaluation.difficulty,
            "near_equivalent_options": list(self.evaluation.near_equivalent_keys),
            "sensitivity_best_options": list(self.evaluation.sensitivity_best_keys),
            "model_sensitive": self.evaluation.model_sensitive,
            "oversized_shove_review": self.evaluation.oversized_shove_review,
        }


@dataclass(frozen=True)
class PreparedPokerRound:
    scenario: PokerScenario
    equity: EquityResult
    evaluation: PokerActionEvaluation
    generation_seconds: float = field(compare=False, default=0.0)
