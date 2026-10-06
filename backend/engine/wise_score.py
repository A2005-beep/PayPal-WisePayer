"""
WiseScore: 0–100 financial health and overdraft-risk score.

Higher score = better protected liquidity, fewer subscription leaks,
healthier discretionary buffer.
"""
from __future__ import annotations
from dataclasses import dataclass
from .cashflow_model import CashflowModel


@dataclass
class WiseScoreResult:
    score: int                   # 0–100
    grade: str                   # A+ / A / B / C / D / F
    liquidity_ratio: float       # available_discretionary / current_balance
    overdraft_risk_days: int     # days in forecast window where balance < minimum_balance
    subscription_waste_annual: float
    insights: list[str]


def compute_wise_score(model: CashflowModel) -> WiseScoreResult:
    """Compute WiseScore from a fully-built CashflowModel."""
    snaps = model.snapshots
    today_snap = model.today_snapshot()

    # ── Component 1: Liquidity buffer ratio (30 pts max)
    liq_ratio = (
        today_snap.available_discretionary / model.current_balance
        if model.current_balance > 0 else 0.0
    )
    liquidity_pts = min(30, int(liq_ratio * 60))

    # ── Component 2: Overdraft risk (25 pts max — penalize bad days)
    danger_days = sum(
        1 for s in snaps
        if s.projected_balance < model.minimum_balance
    )
    overdraft_pts = max(0, 25 - (danger_days * 4))

    # ── Component 3: Subscription leaks penalty (20 pts max)
    leaks = model.subscription_leaks
    annual_waste = sum(l.annual_cost for l in leaks)
    leak_penalty = min(20, int(annual_waste / 50))  # 1 pt per $50 annual waste
    subscription_pts = max(0, 20 - leak_penalty)

    # ── Component 4: Income consistency (15 pts max)
    income_events = [
        e for s in snaps for e in s.events_on_date
        if e.direction == "inflow" and e.confidence >= 0.9
    ]
    income_pts = min(15, len(income_events) * 5)

    # ── Component 5: Confidence band tightness (10 pts max)
    avg_band_width = sum(
        abs(s.confidence_high - s.confidence_low) for s in snaps
    ) / max(1, len(snaps))
    band_pts = max(0, 10 - int(avg_band_width / model.current_balance * 100)) if model.current_balance else 0

    score = liquidity_pts + overdraft_pts + subscription_pts + income_pts + band_pts
    score = max(0, min(100, score))

    # Build insights
    insights: list[str] = []
    if liq_ratio < 0.15:
        insights.append("Your liquid cushion is below 15% of your balance. Avoid new commitments this week.")
    if danger_days > 0:
        insights.append(f"Your balance dips below the minimum buffer on {danger_days} day(s) in the next 30 days.")
    if annual_waste > 200:
        insights.append(f"Subscription services are costing you ${annual_waste:,.0f}/year -- some may be forgotten.")
    if not income_events:
        insights.append("No confirmed income in the next 30 days. Be conservative with large purchases.")
    
    if score >= 80:
        insights.append("Your cashflow is healthy! You're well-protected against overdrafts.")
    elif score >= 60:
        insights.append("Moderate cashflow health. Essential expenses are covered; keep discretionary spending measured.")
    elif not insights:
        insights.append("Cashflow buffer is constrained. Prioritize protecting your minimum balance reserve.")

    # Grade
    if score >= 90:
        grade = "A+"
    elif score >= 80:
        grade = "A"
    elif score >= 70:
        grade = "B"
    elif score >= 60:
        grade = "C"
    elif score >= 50:
        grade = "D"
    else:
        grade = "F"

    return WiseScoreResult(
        score=score,
        grade=grade,
        liquidity_ratio=round(liq_ratio, 3),
        overdraft_risk_days=danger_days,
        subscription_waste_annual=round(annual_waste, 2),
        insights=insights,
    )
