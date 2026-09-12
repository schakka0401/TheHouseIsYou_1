"""Long-horizon bankroll comparison using observed session behavior."""
from __future__ import annotations

import random
import statistics


def _sample_result(stats, rng):
    value = rng.random()
    if value < stats.win_probability:
        return "win"
    if value < stats.win_probability + stats.loss_probability:
        return "loss"
    return "push"


def simulate_long_term_bankroll(records, engine, initial_bankroll, simulations=10_000, horizon=100, seed=None):
    if not records or initial_bankroll <= 0:
        return {"bankruptcy_probability": 1.0 if initial_bankroll <= 0 else 0.0, "median_ending_bankroll": 0.0, "mean_ending_bankroll": 0.0, "p10": 0.0, "p90": 0.0}
    rng = random.Random(seed)
    endings_player, endings_optimal = [], []
    bankrupt_player = bankrupt_optimal = 0
    for _ in range(simulations):
        player_bankroll = optimal_bankroll = initial_bankroll
        player_dead = optimal_dead = False
        for _ in range(horizon):
            record = rng.choice(records)
            bet_fraction = record.bet / max(1, record.bankroll_before)
            player_bet = min(player_bankroll, max(1, round(player_bankroll * bet_fraction))) if player_bankroll else 0
            optimal_bet = player_bet
            if not player_dead:
                action_stats = engine.evaluate(record.scenario)[record.player_action]
                result = _sample_result(action_stats, rng)
                player_bankroll += player_bet if result == "win" else -player_bet if result == "loss" else 0
                if player_bankroll <= 0:
                    player_bankroll = 0
                    player_dead = True
            if not optimal_dead:
                action_stats = engine.evaluate(record.scenario)[record.optimal_action]
                result = _sample_result(action_stats, rng)
                optimal_bankroll += optimal_bet if result == "win" else -optimal_bet if result == "loss" else 0
                if optimal_bankroll <= 0:
                    optimal_bankroll = 0
                    optimal_dead = True
        bankrupt_player += player_dead
        bankrupt_optimal += optimal_dead
        endings_player.append(player_bankroll)
        endings_optimal.append(optimal_bankroll)
    def summary(values, bankrupt):
        values.sort()
        return {"bankruptcy_probability": bankrupt / simulations, "median_ending_bankroll": statistics.median(values), "mean_ending_bankroll": statistics.mean(values), "p10": values[int(len(values) * .10)], "p90": values[int(len(values) * .90) - 1]}
    return {"player": summary(endings_player, bankrupt_player), "optimal": summary(endings_optimal, bankrupt_optimal)}
