"""
WisePayer Cashflow Engine
30-day rolling forecast with confidence bands, subscription leak detection,
and safe discretionary liquidity computation.

Ported and significantly extended from the HackerRank Orchestrate codebase.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional
import math


@dataclass
class FinancialEvent:
    event_id: str
    event_type: str          # income | expense | subscription | pending
    description: str
    amount: float            # in home_currency, always positive
    direction: str           # inflow | outflow
    event_date: date
    is_essential: bool       # rent, insurance, loan repayments, etc.
    is_subscription: bool    # recurring SaaS / entertainment bills
    recurrence_days: Optional[int] = None  # None = one-off
    confidence: float = 1.0  # 0.0–1.0 certainty (1.0 = confirmed)


@dataclass
class CashflowSnapshot:
    """Point-in-time balance projection."""
    snapshot_date: date
    projected_balance: float
    reserved_essential: float   # funds locked for essential bills
    available_discretionary: float  # genuinely free money
    confidence_low: float       # pessimistic balance (90th pct downside)
    confidence_high: float      # optimistic balance
    events_on_date: list[FinancialEvent] = field(default_factory=list)


@dataclass
class SubscriptionLeak:
    event_id: str
    description: str
    amount_per_cycle: float
    recurrence_days: int
    annual_cost: float
    last_seen: date
    category: str  # streaming | gaming | news | fitness | other


class CashflowModel:
    """
    Builds a 30-day rolling cashflow forecast from a list of financial events.

    Responsibilities:
        - Project daily balance forward
        - Compute safe discretionary liquidity (available - essential buffer)
        - Detect subscription leaks
        - Flag safe pay dates for a given target amount
        - Produce confidence bands via Monte Carlo-lite sensitivity
    """

    FORECAST_DAYS = 30
    CONFIDENCE_VOLATILITY = 0.04  # ±4% per-day balance uncertainty

    def __init__(
        self,
        current_balance: float,
        minimum_balance: float,
        events: list[FinancialEvent],
        home_currency: str = "USD",
    ):
        self.current_balance = current_balance
        self.minimum_balance = minimum_balance
        self.events = events
        self.home_currency = home_currency
        self.today = date.today()
        self._snapshots: list[CashflowSnapshot] = []
        self._subscription_leaks: list[SubscriptionLeak] = []
        self._built = False

    # ─────────────────────────────────────────────────────────── build ──────
    def build(self) -> None:
        """Run the full 30-day forward projection."""
        self._snapshots = []
        balance = self.current_balance

        # Pre-compute essential obligations over forecast window
        essential_total = sum(
            e.amount for e in self.events
            if e.is_essential
            and e.direction == "outflow"
            and self.today <= e.event_date <= self.today + timedelta(days=self.FORECAST_DAYS)
        )

        for offset in range(self.FORECAST_DAYS + 1):
            snap_date = self.today + timedelta(days=offset)
            day_events = [e for e in self.events if e.event_date == snap_date]

            for ev in day_events:
                if ev.direction == "inflow":
                    balance += ev.amount * ev.confidence
                else:
                    balance -= ev.amount * ev.confidence

            # Reserved = sum of essential outflows still ahead
            reserved = sum(
                e.amount for e in self.events
                if e.is_essential
                and e.direction == "outflow"
                and snap_date <= e.event_date <= self.today + timedelta(days=self.FORECAST_DAYS)
            )

            # Confidence bands via simple geometric volatility
            vol = balance * self.CONFIDENCE_VOLATILITY * math.sqrt(offset + 1)
            self._snapshots.append(CashflowSnapshot(
                snapshot_date=snap_date,
                projected_balance=round(balance, 2),
                reserved_essential=round(reserved, 2),
                available_discretionary=round(
                    max(0.0, balance - reserved - self.minimum_balance), 2
                ),
                confidence_low=round(balance - vol, 2),
                confidence_high=round(balance + vol, 2),
                events_on_date=day_events,
            ))

        self._detect_subscription_leaks()
        self._built = True

    # ─────────────────────────────────────────────── public API ─────────────
    @property
    def snapshots(self) -> list[CashflowSnapshot]:
        self._assert_built()
        return self._snapshots

    @property
    def subscription_leaks(self) -> list[SubscriptionLeak]:
        self._assert_built()
        return self._subscription_leaks

    def today_snapshot(self) -> CashflowSnapshot:
        self._assert_built()
        return self._snapshots[0]

    def safe_discretionary_today(self) -> float:
        return self.today_snapshot().available_discretionary

    def earliest_safe_date(self, target_amount: float) -> Optional[date]:
        """Return the first date where available_discretionary >= target_amount."""
        self._assert_built()
        for snap in self._snapshots:
            if snap.available_discretionary >= target_amount:
                return snap.snapshot_date
        return None

    def balance_on(self, target_date: date) -> Optional[CashflowSnapshot]:
        self._assert_built()
        for snap in self._snapshots:
            if snap.snapshot_date == target_date:
                return snap
        return None

    def to_dict_list(self) -> list[dict]:
        """Serialize snapshots for AG Grid / JSON API response."""
        self._assert_built()
        rows = []
        for snap in self._snapshots:
            rows.append({
                "date": snap.snapshot_date.isoformat(),
                "projected_balance": snap.projected_balance,
                "reserved_essential": snap.reserved_essential,
                "available_discretionary": snap.available_discretionary,
                "confidence_low": snap.confidence_low,
                "confidence_high": snap.confidence_high,
                "events": [
                    {
                        "event_id": e.event_id,
                        "description": e.description,
                        "amount": e.amount,
                        "direction": e.direction,
                        "is_essential": e.is_essential,
                        "is_subscription": e.is_subscription,
                    }
                    for e in snap.events_on_date
                ],
            })
        return rows

    # ─────────────────────────────────────────── subscription leaks ─────────
    def _detect_subscription_leaks(self) -> None:
        """Identify recurring subscription outflows the user may have forgotten."""
        self._subscription_leaks = []
        seen_ids: set[str] = set()
        for ev in self.events:
            if ev.is_subscription and ev.direction == "outflow" and ev.event_id not in seen_ids:
                seen_ids.add(ev.event_id)
                annual = (365 / (ev.recurrence_days or 30)) * ev.amount
                cat = _classify_subscription(ev.description)
                self._subscription_leaks.append(SubscriptionLeak(
                    event_id=ev.event_id,
                    description=ev.description,
                    amount_per_cycle=ev.amount,
                    recurrence_days=ev.recurrence_days or 30,
                    annual_cost=round(annual, 2),
                    last_seen=ev.event_date,
                    category=cat,
                ))

    def _assert_built(self) -> None:
        if not self._built:
            raise RuntimeError("Call build() before accessing cashflow data.")


# ─────────────────────────────────────────────────── helpers ────────────────
_STREAMING_KEYWORDS = {"netflix", "spotify", "apple tv", "disney", "hulu", "youtube premium", "prime video"}
_GAMING_KEYWORDS = {"xbox", "playstation", "nintendo", "steam", "ea play", "gamepass"}
_FITNESS_KEYWORDS = {"gym", "peloton", "fitness", "strava"}
_NEWS_KEYWORDS = {"new york times", "washington post", "nyt", "medium", "substack"}


def _classify_subscription(description: str) -> str:
    low = description.lower()
    if any(k in low for k in _STREAMING_KEYWORDS):
        return "streaming"
    if any(k in low for k in _GAMING_KEYWORDS):
        return "gaming"
    if any(k in low for k in _FITNESS_KEYWORDS):
        return "fitness"
    if any(k in low for k in _NEWS_KEYWORDS):
        return "news"
    return "other"
