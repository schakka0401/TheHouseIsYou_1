"""Decision records, session statistics, scoring, and console reports."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import statistics


CONFIDENCE_PROBABILITIES = {
    1: 0.55,
    2: 0.60,
    3: 0.65,
    4: 0.70,
    5: 0.75,
    6: 0.80,
    7: 0.85,
    8: 0.90,
    9: 0.95,
    10: 0.99,
}

RISK_THRESHOLD_TOLERANCE = 1e-9
LARGE_WAGER_THRESHOLD = 0.25
EXTREME_WAGER_THRESHOLD = 0.50
ALL_IN_THRESHOLD = 0.95


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
    bankroll_change: int = 0
    dealer_comment: str = ""
    scenario: object = field(default=None, repr=False)

    @property
    def risk_fraction(self) -> float:
        return self.bet / self.bankroll_before if self.bankroll_before else 0.0

    def as_dict(self) -> dict:
        data = asdict(self)
        data.pop("scenario", None)
        data["risk_fraction"] = self.risk_fraction
        return data


def decision_score_components(
    accuracy: float,
    brier_score: float,
    average_ev_regret: float,
    average_risk_fraction: float,
    maximum_risk_fraction: float,
) -> dict[str, float]:
    """Return tunable 0-100 score components.

    Final weighting is 40% decision quality, 25% confidence calibration,
    20% EV efficiency, and 15% bet discipline.
    """
    return {
        "decision_quality": 100.0 * accuracy,
        "confidence_calibration": 100.0 * max(0.0, min(1.0, 1.0 - brier_score)),
        "ev_efficiency": 100.0 * max(0.0, min(1.0, 1.0 - average_ev_regret / 0.25)),
        "bet_discipline": 100.0 * max(
            0.0,
            min(1.0, 1.0 - 0.65 * average_risk_fraction - 0.35 * maximum_risk_fraction),
        ),
    }


def decision_score(components: dict[str, float]) -> int:
    return round(
        0.40 * components["decision_quality"]
        + 0.25 * components["confidence_calibration"]
        + 0.20 * components["ev_efficiency"]
        + 0.15 * components["bet_discipline"]
    )


class DecisionTracker:
    def __init__(self):
        self.records: list[DecisionRecord] = []

    def add(self, record: DecisionRecord) -> None:
        self.records.append(record)

    def analyze(self, engine=None, progress_callback=None) -> dict:
        """Finalize any legacy incomplete records, then calculate the profile."""
        total = len(self.records)
        for index, record in enumerate(self.records, start=1):
            if record.ev_hit is None:
                if engine is None or record.scenario is None:
                    raise RuntimeError(f"Round {record.round_number} has no exact analysis")
                stats = engine.evaluate(record.scenario)
                self.apply_evaluation(record, stats, engine.difficulty)
            if progress_callback:
                progress_callback(index, total)
        return self.profile()

    @staticmethod
    def apply_evaluation(record: DecisionRecord, stats, difficulty_function) -> None:
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
        record.ev_regret = max(0.0, optimal.ev - chosen.ev)
        record.decision_margin = abs(hit_stats.ev - stand_stats.ev)
        record.difficulty = difficulty_function(record.decision_margin)
        record.win_probability_hit = hit_stats.win_probability
        record.loss_probability_hit = hit_stats.loss_probability
        record.push_probability_hit = hit_stats.push_probability
        record.win_probability_stand = stand_stats.win_probability
        record.loss_probability_stand = stand_stats.loss_probability
        record.push_probability_stand = stand_stats.push_probability

    @staticmethod
    def print_round_debug(record: DecisionRecord) -> None:
        def card_short(card: str) -> str:
            rank, suit = card.split(" of ")
            return f"{rank}{suit[0].upper()}"

        print("\n=====================================")
        print(f"ROUND {record.round_number} DEBUG\n")
        print("Player:")
        print(" ".join(card_short(card) for card in record.player_cards))
        print(f"Total: {record.player_total}\n")
        print("Dealer:")
        print(f"{card_short(record.dealer_upcard)}\n")
        print("Player chose:")
        print(f"{record.player_action.upper()}\n")
        print("Confidence:")
        print(f"{record.confidence_level} / 10")
        print(f"{record.confidence_probability:.0%}\n")
        print("Wager:")
        print(f"{record.bet}\n")
        print("HIT:")
        print(f"Win  {record.win_probability_hit:.1%}")
        print(f"Loss {record.loss_probability_hit:.1%}")
        print(f"Push {record.push_probability_hit:.1%}")
        print(f"EV   {record.ev_hit:+.3f}\n")
        print("STAND:")
        print(f"Win  {record.win_probability_stand:.1%}")
        print(f"Loss {record.loss_probability_stand:.1%}")
        print(f"Push {record.push_probability_stand:.1%}")
        print(f"EV   {record.ev_stand:+.3f}\n")
        print("Optimal:")
        print(f"{record.optimal_action.upper()}\n")
        print("Decision correct:")
        print(f"{'YES' if record.decision_correct else 'NO'}\n")
        print("EV regret:")
        print(f"{record.ev_regret:.3f}\n")
        print("Difficulty:")
        print(f"{record.difficulty}\n")
        print("Random outcome:")
        print(f"{record.actual_round_result.upper()}\n")
        print("Bankroll:")
        print(f"{record.bankroll_before} -> {record.bankroll_after}")
        print("=====================================")

    def profile(self) -> dict:
        records = self.records
        total = len(records)
        if not total:
            return {"total_decisions": 0, "accuracy": 0.0, "findings": []}
        correct = sum(bool(record.decision_correct) for record in records)
        accuracy = correct / total
        average_confidence = statistics.mean(record.confidence_probability for record in records)
        calibration_gap = average_confidence - accuracy
        brier = statistics.mean(
            (record.confidence_probability - int(bool(record.decision_correct))) ** 2
            for record in records
        )
        wager_total = sum(record.bet for record in records)
        weighted_accuracy = (
            sum(record.bet * int(bool(record.decision_correct)) for record in records) / wager_total
            if wager_total else 0.0
        )
        regrets = [float(record.ev_regret or 0.0) for record in records]
        risk_fractions = [record.risk_fraction for record in records]
        average_regret = statistics.mean(regrets)
        average_risk = statistics.mean(risk_fractions)
        maximum_risk = max(risk_fractions)
        large_wager_count = sum(
            risk + RISK_THRESHOLD_TOLERANCE >= LARGE_WAGER_THRESHOLD
            for risk in risk_fractions
        )
        extreme_wager_count = sum(
            risk + RISK_THRESHOLD_TOLERANCE >= EXTREME_WAGER_THRESHOLD
            for risk in risk_fractions
        )
        all_in_count = sum(
            risk + RISK_THRESHOLD_TOLERANCE >= ALL_IN_THRESHOLD
            for risk in risk_fractions
        )
        player_hit_rate = sum(record.player_action == "hit" for record in records) / total
        optimal_hit_rate = sum(record.optimal_action == "hit" for record in records) / total
        components = decision_score_components(accuracy, brier, average_regret, average_risk, maximum_risk)
        starting_bankroll = records[0].bankroll_before
        actual_bankroll = records[-1].bankroll_after
        expected_player_bankroll = starting_bankroll + sum(record.bet * float(record.ev_chosen) for record in records)
        expected_optimal_bankroll = starting_bankroll + sum(record.bet * float(record.ev_optimal) for record in records)
        luck_gap = actual_bankroll - expected_player_bankroll
        profile = {
            "total_decisions": total,
            "correct_decisions": correct,
            "accuracy": accuracy,
            "average_confidence": average_confidence,
            "calibration_gap": calibration_gap,
            "brier_score": brier,
            "bet_weighted_accuracy": weighted_accuracy,
            "player_hit_rate": player_hit_rate,
            "optimal_hit_rate": optimal_hit_rate,
            "total_ev_regret": sum(regrets),
            "average_ev_regret": average_regret,
            "average_risk_fraction": average_risk,
            "maximum_risk_fraction": maximum_risk,
            "large_wager_count": large_wager_count,
            "extreme_wager_count": extreme_wager_count,
            "all_in_count": all_in_count,
            "starting_bankroll": starting_bankroll,
            "actual_bankroll": actual_bankroll,
            "expected_player_bankroll": expected_player_bankroll,
            "expected_optimal_bankroll": expected_optimal_bankroll,
            "luck_gap": luck_gap,
            "decision_score": decision_score(components),
            "score_components": {name: round(value) for name, value in components.items()},
        }
        profile["findings"] = self.result_findings(profile)
        return profile

    @staticmethod
    def result_findings(profile: dict, projection: dict | None = None) -> list[str]:
        """Tell separate decision-quality, risk-sizing, and luck stories."""
        accuracy = profile["accuracy"]
        correct = profile["correct_decisions"]
        total = profile["total_decisions"]
        average_regret = profile["average_ev_regret"]
        if accuracy >= 0.90:
            decision_finding = f"You chose the higher-EV action on {correct} of {total} decisions."
        elif accuracy >= 0.70:
            decision_finding = f"Your card decisions were strong: {correct} of {total} were higher-EV."
        elif correct < total and average_regret < 0.04:
            decision_finding = "Several card mistakes were close and cost little expected value."
        elif profile["player_hit_rate"] - profile["optimal_hit_rate"] > 0.15:
            decision_finding = "You hit more often than the higher-EV strategy called for."
        elif profile["optimal_hit_rate"] - profile["player_hit_rate"] > 0.15:
            decision_finding = "You stood more often than the higher-EV strategy called for."
        else:
            decision_finding = f"You chose the higher-EV action on {correct} of {total} decisions."

        all_in_count = profile["all_in_count"]
        maximum_risk = profile["maximum_risk_fraction"]
        large_wager_count = profile["large_wager_count"]
        risk_driven = False
        if projection:
            observed = projection["player"]["bankruptcy_probability"]
            same_bets = projection["optimal"]["bankruptcy_probability"]
            capped = projection["risk_capped"]["bankruptcy_probability"]
            decision_effect = abs(observed - same_bets)
            risk_cap_effect = same_bets - capped
            risk_driven = (
                same_bets >= 0.50
                and risk_cap_effect >= 0.15
                and risk_cap_effect > decision_effect
            )
        if all_in_count:
            if risk_driven and accuracy >= 0.80:
                risk_finding = "An all-in wager drove most projected risk, despite strong card decisions."
            elif risk_driven:
                risk_finding = "An all-in wager drove most of your projected long-term risk."
            else:
                risk_finding = "You put nearly your entire bankroll at risk on a single decision."
        elif maximum_risk + RISK_THRESHOLD_TOLERANCE >= EXTREME_WAGER_THRESHOLD:
            if risk_driven:
                risk_finding = "Aggressive wager sizing drove most of your projected long-term risk."
            else:
                risk_finding = "Your largest wager exposed more than half your bankroll to one outcome."
        elif large_wager_count >= 2:
            risk_finding = "Several wagers exposed at least a quarter of your bankroll."
        else:
            risk_finding = "Your wager sizing was relatively controlled."

        luck_gap = profile["luck_gap"]
        luck_threshold = max(5.0, profile["starting_bankroll"] * 0.10)
        if luck_gap > luck_threshold:
            luck_finding = "Your final bankroll finished well above expectation; luck was on your side."
        elif luck_gap < -luck_threshold:
            luck_finding = "Your bankroll finished below expectation; your decisions were better than the chip count suggests."
        else:
            luck_finding = "Your final bankroll was reasonably close to the expected value of your choices."
        return [decision_finding, risk_finding, luck_finding]

    @staticmethod
    def print_session_report(profile: dict, projection: dict) -> None:
        profile["findings"] = DecisionTracker.result_findings(profile, projection)
        gap = profile["calibration_gap"]
        if gap > 0:
            calibration_sentence = f"You were overconfident by approximately {abs(gap):.0%}."
        elif gap < 0:
            calibration_sentence = f"You were underconfident by approximately {abs(gap):.0%}."
        else:
            calibration_sentence = "Your average confidence matched your accuracy."
        player_projection = projection["player"]
        optimal_projection = projection["optimal"]
        capped_projection = projection["risk_capped"]

        print("\n========================================")
        print("           THE HOUSE SAYS")
        print("========================================\n")
        print("DECISION SCORE")
        print(f"{profile['decision_score']} / 100\n")
        print("OPTIMAL DECISIONS")
        print(f"{profile['correct_decisions']} / {profile['total_decisions']}\n")
        print("CONFIDENCE")
        print(f"Average confidence: {profile['average_confidence']:.0%}")
        print(f"Actual accuracy:     {profile['accuracy']:.0%}\n")
        print(calibration_sentence)
        print("\nBANKROLL")
        print("Actual result")
        print(f"{profile['actual_bankroll']} chips\n")
        print("Expected from your choices")
        print(f"{profile['expected_player_bankroll']:.1f} chips\n")
        print("Expected with optimal HIT/STAND")
        print(f"{profile['expected_optimal_bankroll']:.1f} chips")
        print("Expected values use the same wagers you placed.\n")
        print("WHAT THE HOUSE NOTICED\n")
        for finding in profile["findings"]:
            print(f"- {finding}")
        print("\nLONG-TERM SIMULATION")
        print(f"{projection['simulations']:,} simulated {projection['horizon']}-decision sessions")
        print("Simulation based on repeating your observed betting behavior.\n")
        print(f"Your choices + your betting:       {player_projection['bankruptcy_probability']:.0%} bankruptcy")
        print(f"Optimal HIT/STAND + your betting:  {optimal_projection['bankruptcy_probability']:.0%} bankruptcy")
        print(
            f"Optimal HIT/STAND + {projection['risk_cap']:.0%} risk cap: "
            f"{capped_projection['bankruptcy_probability']:.0%} bankruptcy"
        )
        print("\n        CARE TO PROVE ME WRONG?")
        print("========================================")
        print("\nDETAILED DEBUG STATISTICS")
        print(f"Brier score:             {profile['brier_score']:.4f}")
        print(f"Total EV regret:         {profile['total_ev_regret']:.4f}")
        print(f"Average EV regret:       {profile['average_ev_regret']:.4f}")
        print(f"Player HIT rate:         {profile['player_hit_rate']:.1%}")
        print(f"Optimal HIT rate:        {profile['optimal_hit_rate']:.1%}")
        print(f"Bet-weighted accuracy:   {profile['bet_weighted_accuracy']:.1%}")
        print(f"Average risk fraction:   {profile['average_risk_fraction']:.1%}")
        print(f"Maximum risk fraction:   {profile['maximum_risk_fraction']:.1%}")
        for name, value in profile["score_components"].items():
            print(f"{name.replace('_', ' ').title():24}{value}")
        for label, summary in (
            ("Observed", player_projection),
            ("Optimal same bets", optimal_projection),
            ("Optimal capped", capped_projection),
        ):
            print(f"{label} mean/median:      {summary['mean_ending_bankroll']:.1f} / {summary['median_ending_bankroll']:.1f}")
            print(f"{label} p10/p90:         {summary['p10']:.1f} / {summary['p90']:.1f}")

        print("\nRISK ANALYSIS")
        print(f"Average wager fraction:                 {profile['average_risk_fraction']:.1%}")
        print(f"Maximum wager fraction:                 {profile['maximum_risk_fraction']:.1%}")
        print(f"25%+ bankroll wagers:                   {profile['large_wager_count']}")
        print(f"50%+ bankroll wagers:                   {profile['extreme_wager_count']}")
        print(f"All-in / near-all-in wagers:            {profile['all_in_count']}")
        print(f"Actual ending bankroll:                 {profile['actual_bankroll']:.1f}")
        print(f"Expected bankroll from chosen actions:  {profile['expected_player_bankroll']:.1f}")
        print(f"Expected bankroll with optimal HIT/STAND: {profile['expected_optimal_bankroll']:.1f}")
        print(f"Luck gap:                               {profile['luck_gap']:+.1f}")
        print(f"\n{projection['horizon']}-decision bankruptcy:")
        print(f"Player decisions + player bets:         {player_projection['bankruptcy_probability']:.1%}")
        print(f"Optimal decisions + player bets:        {optimal_projection['bankruptcy_probability']:.1%}")
        print(
            f"Optimal decisions + {projection['risk_cap']:.0%} cap:       "
            f"{capped_projection['bankruptcy_probability']:.1%}"
        )
