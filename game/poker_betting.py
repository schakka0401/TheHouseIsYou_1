"""Legal no-limit betting-history construction for Poker scenarios."""
from __future__ import annotations

from dataclasses import dataclass

from game.poker_models import PokerAction


@dataclass
class BettingSeat:
    stack: int
    contribution: int = 0
    folded: bool = False
    status: str = "WAITING"


class PokerActionHistory:
    """Build one legal betting-round prefix until action reaches Hero.

    Amounts for BET and RAISE are total contributions on the current street.
    CALL amounts are the chips added by that call. Forced blind posts are
    recorded but do not consume a player's normal turn.
    """

    def __init__(
        self,
        action_order: tuple[str, ...],
        stacks: dict[str, int],
        starting_pot: int,
        big_blind: int = 10,
    ) -> None:
        if set(action_order) != set(stacks):
            raise ValueError("Action order and stack seats must match")
        self.action_order = action_order
        self.seats = {position: BettingSeat(stack) for position, stack in stacks.items()}
        self.starting_pot = starting_pot
        self.pot = starting_pot
        self.big_blind = big_blind
        self.current_bet = 0
        self.last_full_raise = big_blind
        self.actions: list[PokerAction] = []
        self._next_index = 0

    def post(self, actor: str, amount: int) -> None:
        seat = self._seat(actor)
        if amount <= 0 or amount > seat.stack:
            raise ValueError("Forced post must fit within the player's stack")
        seat.stack -= amount
        seat.contribution += amount
        self.pot += amount
        self.current_bet = max(self.current_bet, seat.contribution)
        seat.status = f"POSTED {amount}"
        self.actions.append(PokerAction(actor, "post", amount))

    def act(self, actor: str, action: str, amount: int = 0) -> None:
        expected = self.next_actor
        if actor != expected:
            raise ValueError(f"Action out of order: expected {expected}, got {actor}")
        seat = self._seat(actor)
        if seat.folded:
            raise ValueError("A folded player cannot act")
        to_call = max(0, self.current_bet - seat.contribution)
        action = action.lower()

        if action == "check":
            if to_call:
                raise ValueError("Cannot check while facing a live bet")
            seat.status = "CHECKED"
        elif action == "fold":
            if not to_call:
                raise ValueError("Generated scenarios do not fold when checking is free")
            seat.folded = True
            seat.status = "FOLDED"
        elif action == "call":
            if not to_call:
                raise ValueError("Cannot call when no bet is outstanding")
            paid = min(to_call, seat.stack)
            if amount not in (0, paid):
                raise ValueError(f"Call must add exactly {paid} chips")
            self._commit(seat, paid)
            amount = paid
            seat.status = f"CALLED {paid}"
        elif action == "bet":
            if self.current_bet:
                raise ValueError("Cannot bet into an already-opened pot; use raise")
            self._raise_or_bet(seat, amount)
            seat.status = f"BET {amount}"
        elif action == "raise":
            if not self.current_bet:
                raise ValueError("Cannot raise before a bet exists")
            self._raise_or_bet(seat, amount)
            seat.status = f"RAISED TO {amount}"
        else:
            raise ValueError(f"Unknown poker action: {action}")

        self.actions.append(PokerAction(actor, action, amount))
        self._next_index += 1

    @property
    def next_actor(self) -> str | None:
        while self._next_index < len(self.action_order):
            actor = self.action_order[self._next_index]
            if not self.seats[actor].folded:
                return actor
            self._next_index += 1
        return None

    @property
    def minimum_raise_to(self) -> int:
        if self.current_bet == 0:
            return self.big_blind
        return self.current_bet + max(self.last_full_raise, self.big_blind)

    def _raise_or_bet(self, seat: BettingSeat, raise_to: int) -> None:
        maximum = seat.contribution + seat.stack
        minimum = self.minimum_raise_to
        if raise_to <= self.current_bet or raise_to > maximum:
            raise ValueError("Bet/raise amount lies outside stack bounds")
        all_in = raise_to == maximum
        if raise_to < minimum and not all_in:
            raise ValueError(f"Raise to {raise_to} is below legal minimum {minimum}")
        previous_bet = self.current_bet
        paid = raise_to - seat.contribution
        self._commit(seat, paid)
        raise_increment = raise_to - previous_bet
        if raise_increment >= self.last_full_raise:
            self.last_full_raise = raise_increment
        self.current_bet = raise_to

    def _commit(self, seat: BettingSeat, amount: int) -> None:
        if amount < 0 or amount > seat.stack:
            raise ValueError("Action exceeds available stack")
        seat.stack -= amount
        seat.contribution += amount
        self.pot += amount

    def _seat(self, actor: str) -> BettingSeat:
        try:
            return self.seats[actor]
        except KeyError as error:
            raise ValueError(f"Unknown table position: {actor}") from error
