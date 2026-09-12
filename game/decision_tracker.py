"""Decision records, calibration metrics, score, and neutral findings."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
import statistics


CONFIDENCE_PROBABILITIES = {level: (0.55 + (level - 1) * 0.05 if level < 10 else 0.99) for level in range(1, 11)}


def confidence_probability(level: int) -> float:
    return CONFIDENCE_PROBABILITIES[level]


@dataclass
class DecisionRecord:
    round_number: int
    player_cards: list[str]
    player_total: int
    dealer_upcard: str
    player_action: str
    confidence_level: int
    confidence_probability: float
    bet: int
    bankroll_before: int
    bankroll_after: int
    actual_round_result: str
    optimal_action: str | None = None
    decision_correct: bool | None = None
    ev_hit: float | None = None
    ev_stand: float | None = None
    ev_chosen: float | None = None
    ev_optimal: float | None = None
    ev_regret: float | None = None
    decision_margin: float | None = None
    difficulty: str | None = None
    win_probability_hit: float | None = None
    loss_probability_hit: float | None = None
    push_probability_hit: float | None = None
    win_probability_stand: float | None = None
    loss_probability_stand: float | None = None
    push_probability_stand: float | None = None
    scenario: object = field(default=None, repr=False)

    def as_dict(self):
        data = asdict(self)
        data.pop("scenario", None)
        return data


def _correlation(xs: list[float], ys: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    mean_x, mean_y = statistics.mean(xs), statistics.mean(ys)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    denominator = math.sqrt(sum((x - mean_x) ** 2 for x in xs) * sum((y - mean_y) ** 2 for y in ys))
    return numerator / denominator if denominator else 0.0


class DecisionTracker:
    def __init__(self):
        self.records: list[DecisionRecord] = []

    def add(self, record: DecisionRecord) -> None:
        self.records.append(record)

    def analyze(self, engine, progress_callback=None) -> dict:
        """Add expensive EV analysis after gameplay has finished.

        A local cache ensures repeated strategic states are evaluated only once,
        even if the engine cache is replaced or cleared between sessions.
        """
        cache = {}
        total = len(self.records)
        for index, record in enumerate(self.records, start=1):
            if record.scenario is None:
                raise RuntimeError(f"Round {record.round_number} has no scenario for analysis")
            stats = cache.get(record.scenario.key)
            if stats is None:
                stats = engine.evaluate(record.scenario)
                cache[record.scenario.key] = stats

            hit_stats = stats["hit"]
            stand_stats = stats["stand"]
            optimal_action = "hit" if hit_stats.ev > stand_stats.ev else "stand"
            chosen = stats[record.player_action]
            optimal = stats[optimal_action]

            record.ev_hit = hit_stats.ev
            record.ev_stand = stand_stats.ev
            record.optimal_action = optimal_action
            record.decision_correct = record.player_action == optimal_action
            record.ev_chosen = chosen.ev
            record.ev_optimal = optimal.ev
            record.ev_regret = optimal.ev - chosen.ev
            record.decision_margin = abs(hit_stats.ev - stand_stats.ev)
            record.difficulty = engine.difficulty(record.decision_margin)
            record.win_probability_hit = hit_stats.win_probability
            record.loss_probability_hit = hit_stats.loss_probability
            record.push_probability_hit = hit_stats.push_probability
            record.win_probability_stand = stand_stats.win_probability
            record.loss_probability_stand = stand_stats.loss_probability
            record.push_probability_stand = stand_stats.push_probability

            self.print_analysis(record)
            if progress_callback:
                progress_callback(index, total)
        return self.profile()

    @staticmethod
    def print_analysis(record: DecisionRecord) -> None:
        print("\n---")
        print(f"ROUND {record.round_number} ANALYSIS")
        print(f"Player cards: {' + '.join(record.player_cards)}")
        print(f"Dealer: {record.dealer_upcard}")
        print(f"\nPlayer chose: {record.player_action.upper()}")
        print(f"Confidence: {record.confidence_level}/10 = {record.confidence_probability:.0%}")
        print(f"Bet: {record.bet} chips")
        print(f"\nHIT EV: {record.ev_hit:.3f}")
        print(f"STAND EV: {record.ev_stand:.3f}")
        print(f"\nOptimal: {record.optimal_action.upper()}")
        print(f"Correct decision: {'YES' if record.decision_correct else 'NO'}")
        print(f"EV regret: {record.ev_regret:.3f}")
        print(f"Decision margin: {record.decision_margin:.3f}")
        print("----")

    def profile(self) -> dict:
        records = self.records
        total = len(records)
        if not total:
            return {"total_decisions": 0, "accuracy": 0.0, "findings": []}
        accuracy = sum(r.decision_correct for r in records) / total
        average_confidence = statistics.mean(r.confidence_probability for r in records)
        calibration_gap = average_confidence - accuracy
        brier = statistics.mean((r.confidence_probability - int(r.decision_correct)) ** 2 for r in records)
        wager_total = sum(r.bet for r in records)
        bet_weighted_accuracy = sum(r.bet * int(r.decision_correct) for r in records) / wager_total if wager_total else 0.0
        hit_records = [r for r in records if r.player_action == "hit"]
        stand_records = [r for r in records if r.player_action == "stand"]
        player_hit_rate = len(hit_records) / total
        optimal_hit_rate = sum(r.optimal_action == "hit" for r in records) / total
        ev_regret = [r.ev_optimal - r.ev_chosen for r in records]
        components = self.score_components(accuracy, brier, bet_weighted_accuracy, ev_regret, records)
        score = round(100 * (0.40 * components["decision_quality"] + 0.25 * components["confidence_calibration"] + 0.20 * components["bet_discipline"] + 0.15 * components["ev_efficiency"]))
        by_confidence = {}
        for level in range(1, 11):
            group = [r for r in records if r.confidence_level == level]
            if group:
                by_confidence[level] = {"reported_probability": group[0].confidence_probability, "accuracy": sum(r.decision_correct for r in group) / len(group), "count": len(group)}
        return {
            "total_decisions": total,
            "accuracy": accuracy,
            "average_confidence": average_confidence,
            "calibration_gap": calibration_gap,
            "brier_score": brier,
            "average_wager": statistics.mean(r.bet for r in records),
            "average_bet_fraction": statistics.mean(r.bet / r.bankroll_before for r in records if r.bankroll_before) if any(r.bankroll_before for r in records) else 0.0,
            "bet_weighted_accuracy": bet_weighted_accuracy,
            "confidence_bet_correlation": _correlation([r.confidence_probability for r in records], [r.bet / max(1, r.bankroll_before) for r in records]),
            "accuracy_by_confidence": by_confidence,
            "hit_accuracy": sum(r.optimal_action == "hit" for r in hit_records) / len(hit_records) if hit_records else 0.0,
            "stand_accuracy": sum(r.optimal_action == "stand" for r in stand_records) / len(stand_records) if stand_records else 0.0,
            "player_hit_rate": player_hit_rate,
            "optimal_hit_rate": optimal_hit_rate,
            "total_ev_regret": sum(ev_regret),
            "average_ev_regret": statistics.mean(ev_regret),
            "decision_score": score,
            "score_components": {
                "decision_quality": round(100 * components["decision_quality"]),
                "confidence_calibration": round(100 * components["confidence_calibration"]),
                "bet_discipline": round(100 * components["bet_discipline"]),
                "ev_efficiency": round(100 * components["ev_efficiency"]),
            },
            "findings": self.findings(calibration_gap, player_hit_rate, optimal_hit_rate, bet_weighted_accuracy, accuracy, statistics.mean(r.bet / max(1, r.bankroll_before) for r in records), statistics.mean(ev_regret)),
        }

    @staticmethod
    def score_components(accuracy, brier, weighted_accuracy, regrets, records) -> dict[str, float]:
        return {
            "decision_quality": accuracy,
            "confidence_calibration": max(0.0, min(1.0, 1.0 - brier)),
            "bet_discipline": max(0.0, min(1.0, 0.5 * weighted_accuracy + 0.5 * (1.0 - statistics.mean(r.bet / max(1, r.bankroll_before) for r in records)))),
            "ev_efficiency": max(0.0, min(1.0, 1.0 - max(0.0, statistics.mean(regrets)))),
        }

    @staticmethod
    def decision_score(accuracy, brier, calibration_gap, weighted_accuracy, regrets, records) -> int:
        components = DecisionTracker.score_components(accuracy, brier, weighted_accuracy, regrets, records)
        return round(100 * (0.40 * components["decision_quality"] + 0.25 * components["confidence_calibration"] + 0.20 * components["bet_discipline"] + 0.15 * components["ev_efficiency"]))

    @staticmethod
    def findings(gap, hit_rate, optimal_hit_rate, weighted_accuracy, accuracy, bet_fraction, regret):
        findings = []
        if gap > 0.10:
            findings.append("You were substantially overconfident.")
        elif gap > 0.05:
            findings.append("You were moderately overconfident.")
        elif gap < -0.05:
            findings.append("You tended to underestimate your own accuracy.")
        else:
            findings.append("Your confidence was reasonably well calibrated.")
        if hit_rate - optimal_hit_rate > 0.15:
            findings.append("You hit substantially more often than the optimal strategy.")
        if weighted_accuracy + 0.10 < accuracy:
            findings.append("Your largest bets were concentrated on weaker decisions.")
        if bet_fraction > 0.35:
            findings.append("Your bet sizing exposed a large portion of your bankroll to individual decisions.")
        if regret < 0.04:
            findings.append("Several mistakes were close decisions with relatively little expected-value cost.")
        return findings[:4]
