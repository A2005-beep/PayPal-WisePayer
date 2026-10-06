"""
Backend integration tests.
Run with: pytest backend/tests/ -v
"""
import pytest
from datetime import date, timedelta
from backend.engine.cashflow_model import CashflowModel, FinancialEvent
from backend.engine.wise_score import compute_wise_score


def make_events(balance: float) -> list[FinancialEvent]:
    today = date.today()
    return [
        FinancialEvent("rent", "expense", "Rent", balance * 0.30, "outflow",
                       today + timedelta(days=5), is_essential=True, is_subscription=False),
        FinancialEvent("salary", "income", "Salary", balance * 0.70, "inflow",
                       today + timedelta(days=10), is_essential=False, is_subscription=False, confidence=0.95),
        FinancialEvent("netflix", "subscription", "Netflix", 15.99, "outflow",
                       today + timedelta(days=7), is_essential=False, is_subscription=True, recurrence_days=30),
        FinancialEvent("spotify", "subscription", "Spotify", 9.99, "outflow",
                       today + timedelta(days=12), is_essential=False, is_subscription=True, recurrence_days=30),
    ]


class TestCashflowModel:
    def test_build_produces_31_snapshots(self):
        model = CashflowModel(1000, 200, make_events(1000))
        model.build()
        assert len(model.snapshots) == 31  # today + 30 days

    def test_safe_discretionary_is_non_negative(self):
        model = CashflowModel(1000, 200, make_events(1000))
        model.build()
        for snap in model.snapshots:
            assert snap.available_discretionary >= 0

    def test_confidence_bands_wrap_balance(self):
        model = CashflowModel(1000, 200, make_events(1000))
        model.build()
        for snap in model.snapshots:
            assert snap.confidence_low <= snap.projected_balance <= snap.confidence_high

    def test_subscription_leak_detection(self):
        model = CashflowModel(1000, 200, make_events(1000))
        model.build()
        leaks = model.subscription_leaks
        assert len(leaks) == 2
        descriptions = [l.description for l in leaks]
        assert "Netflix" in descriptions
        assert "Spotify" in descriptions

    def test_subscription_annual_cost(self):
        model = CashflowModel(1000, 200, make_events(1000))
        model.build()
        netflix = next(l for l in model.subscription_leaks if "Netflix" in l.description)
        assert abs(netflix.annual_cost - (365 / 30 * 15.99)) < 1.0

    def test_earliest_safe_date_found_when_salary_arrives(self):
        model = CashflowModel(300, 200, make_events(1000))
        model.build()
        # Safe date for $200 purchase should exist after salary arrives
        safe_date = model.earliest_safe_date(200)
        assert safe_date is not None

    def test_serialization_to_dict_list(self):
        model = CashflowModel(1000, 200, make_events(1000))
        model.build()
        rows = model.to_dict_list()
        assert len(rows) == 31
        assert "date" in rows[0]
        assert "projected_balance" in rows[0]
        assert "available_discretionary" in rows[0]


class TestWiseScore:
    def test_score_range(self):
        model = CashflowModel(1000, 200, make_events(1000))
        model.build()
        result = compute_wise_score(model)
        assert 0 <= result.score <= 100

    def test_grade_matches_score(self):
        model = CashflowModel(1000, 200, make_events(1000))
        model.build()
        result = compute_wise_score(model)
        if result.score >= 80:
            assert result.grade in ("A+", "A")
        elif result.score >= 60:
            assert result.grade in ("B", "C")
        else:
            assert result.grade in ("D", "F")

    def test_low_balance_lowers_score(self):
        high_model = CashflowModel(5000, 200, make_events(5000))
        high_model.build()
        low_model = CashflowModel(250, 200, make_events(250))
        low_model.build()
        assert compute_wise_score(high_model).score > compute_wise_score(low_model).score

    def test_insights_non_empty_on_poor_cashflow(self):
        model = CashflowModel(210, 200, make_events(210))
        model.build()
        result = compute_wise_score(model)
        assert len(result.insights) > 0
