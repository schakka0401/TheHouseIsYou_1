"""Bootstrap long-horizon bankroll comparison from observed decisions."""
from __future__ import annotations

import random
import statistics


RISK_CAP = 0.10


def _sample_result(probabilities: tuple[float, float, float], rng: random.Random) -> str:
    win_probability, loss_probability, _ = probabilities
    value = rng.random()
    if value < win_probability:
        return "win"
    if value < win_probability + loss_probability:
        return "loss"
    return "push"


def _probabilities(record, action: str) -> tuple[float, float, float]:
    if action == "hit":
        return (
            record.win_probability_hit,
            record.loss_probability_hit,
            record.push_probability_hit,
        )
    return (
        record.win_probability_stand,
        record.loss_probability_stand,
        record.push_probability_stand,
    )


def _wager(bankroll: int, risk_fraction: float) -> int:
    return min(bankroll, max(1, round(bankroll * risk_fraction))) if bankroll > 0 else 0


def simulate_long_term_bankroll(
    records,
    engine=None,
    initial_bankroll=0,
    simulations=10_000,
    horizon=100,
    seed=None,
    risk_cap=RISK_CAP,
):
    """Compare card decisions separately from observed and capped wager risk.

    ``player`` repeats both the player's chosen actions and observed wager
    fractions. ``optimal`` changes only HIT/STAND while retaining those same
    wager fractions. ``risk_capped`` also limits each sampled fraction to the
    configured conservative benchmark; it is not a bet-sizing prescription.
    """
    risk_cap = max(0.0, min(1.0, float(risk_cap)))
    if not records or initial_bankroll <= 0:
        empty = {
            "bankruptcy_probability": 1.0 if initial_bankroll <= 0 else 0.0,
            "median_ending_bankroll": 0.0,
            "mean_ending_bankroll": 0.0,
            "p10": 0.0,
            "p90": 0.0,
        }
        return {
            "simulations": simulations,
            "horizon": horizon,
            "risk_cap": risk_cap,
            "player": empty,
            "optimal": empty.copy(),
            "risk_capped": empty.copy(),
        }

    rng = random.Random(seed)
    player_endings = []
    optimal_endings = []
    capped_endings = []
    player_bankruptcies = 0
    optimal_bankruptcies = 0
    capped_bankruptcies = 0

    for _ in range(simulations):
        player_bankroll = initial_bankroll
        optimal_bankroll = initial_bankroll
        capped_bankroll = initial_bankroll
        player_bankrupt = False
        optimal_bankrupt = False
        capped_bankrupt = False
        for _ in range(horizon):
            # Both trajectories see the same sampled scenario and betting style.
            record = rng.choice(records)
            risk_fraction = record.risk_fraction
            if not player_bankrupt:
                player_bet = _wager(player_bankroll, risk_fraction)
                result = _sample_result(_probabilities(record, record.player_action), rng)
                player_bankroll += player_bet if result == "win" else -player_bet if result == "loss" else 0
                if player_bankroll <= 0:
                    player_bankroll = 0
                    player_bankrupt = True
            if not optimal_bankrupt:
                optimal_bet = _wager(optimal_bankroll, risk_fraction)
                result = _sample_result(_probabilities(record, record.optimal_action), rng)
                optimal_bankroll += optimal_bet if result == "win" else -optimal_bet if result == "loss" else 0
                if optimal_bankroll <= 0:
                    optimal_bankroll = 0
                    optimal_bankrupt = True
            if not capped_bankrupt:
                capped_fraction = min(risk_fraction, risk_cap)
                capped_bet = _wager(capped_bankroll, capped_fraction)
                result = _sample_result(_probabilities(record, record.optimal_action), rng)
                capped_bankroll += capped_bet if result == "win" else -capped_bet if result == "loss" else 0
                if capped_bankroll <= 0:
                    capped_bankroll = 0
                    capped_bankrupt = True
        player_bankruptcies += player_bankrupt
        optimal_bankruptcies += optimal_bankrupt
        capped_bankruptcies += capped_bankrupt
        player_endings.append(player_bankroll)
        optimal_endings.append(optimal_bankroll)
        capped_endings.append(capped_bankroll)

    def summary(values: list[int], bankruptcies: int) -> dict[str, float]:
        ordered = sorted(values)
        return {
            "bankruptcy_probability": bankruptcies / simulations,
            "median_ending_bankroll": statistics.median(ordered),
            "mean_ending_bankroll": statistics.mean(ordered),
            "p10": ordered[round((len(ordered) - 1) * 0.10)],
            "p90": ordered[round((len(ordered) - 1) * 0.90)],
        }

    return {
        "simulations": simulations,
        "horizon": horizon,
        "risk_cap": risk_cap,
        "player": summary(player_endings, player_bankruptcies),
        "optimal": summary(optimal_endings, optimal_bankruptcies),
        "risk_capped": summary(capped_endings, capped_bankruptcies),
    }
