"""
Self-contained verification suite for PayPal WisePayer.
Tests core cashflow forecasting, WiseScore, BuyerAgent logic, A2A MerchantAgent,
and subscription leak detection without requiring external dependencies like pytest.
"""
import sys
import os
from pathlib import Path
from datetime import date, timedelta

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Handle Windows terminal encoding
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from backend.engine.cashflow_model import CashflowModel, FinancialEvent
from backend.engine.wise_score import compute_wise_score
from backend.agent.merchant_agent import MerchantAgent, NegotiationRequest
from backend.agent.buyer_agent import BuyerAgent, AutonomyLevel, PurchaseRequest
from backend.paypal.sandbox_client import PayPalSandboxClient


def test_cashflow_and_leaks():
    print("[1/5] Testing Cashflow Engine & Subscription Leaks...")
    today = date.today()
    balance = 1420.0
    min_balance = 200.0

    events = [
        FinancialEvent("rent", "expense", "Rent", 800.0, "outflow", today + timedelta(days=4), is_essential=True, is_subscription=False),
        FinancialEvent("insurance", "expense", "Car Insurance", 150.0, "outflow", today + timedelta(days=2), is_essential=True, is_subscription=False),
        FinancialEvent("salary", "income", "Salary", 1800.0, "inflow", today + timedelta(days=10), is_essential=False, is_subscription=False, confidence=0.95),
        FinancialEvent("netflix", "subscription", "Netflix 4K", 19.99, "outflow", today + timedelta(days=6), is_essential=False, is_subscription=True, recurrence_days=30),
        FinancialEvent("gym", "subscription", "Equinox Gym", 55.00, "outflow", today + timedelta(days=1), is_essential=False, is_subscription=True, recurrence_days=30),
        FinancialEvent("nyt", "subscription", "NYTimes All Access", 4.00, "outflow", today + timedelta(days=15), is_essential=False, is_subscription=True, recurrence_days=30),
    ]

    model = CashflowModel(balance, min_balance, events)
    model.build()

    assert len(model.snapshots) == 31, f"Expected 31 snapshots, got {len(model.snapshots)}"
    today_snap = model.today_snapshot()
    
    # Balance: 1420. Reserved essentials: Rent (800) + Insurance (150) = 950.
    # Minimum buffer: 200.
    # Available discretionary = 1420 - 950 - 200 = 270.
    assert today_snap.reserved_essential == 950.0, f"Expected reserved 950.0, got {today_snap.reserved_essential}"
    assert today_snap.available_discretionary == 270.0, f"Expected safe discretionary 270.0, got {today_snap.available_discretionary}"

    # Verify subscription leak detection
    leaks = model.subscription_leaks
    assert len(leaks) == 3, f"Expected 3 leaks, got {len(leaks)}"
    leak_names = {l.description for l in leaks}
    assert "Netflix 4K" in leak_names
    assert "Equinox Gym" in leak_names
    assert "NYTimes All Access" in leak_names

    # Check safe pay date for an $850 laptop
    # Before day 10 (salary), available is <= 270. On day 10, salary adds 1800 * 0.95 = 1710.
    safe_date = model.earliest_safe_date(850.0)
    assert safe_date is not None, "Expected safe date after salary arrival"
    assert safe_date == today + timedelta(days=10), f"Expected safe date {today + timedelta(days=10)}, got {safe_date}"

    print("   [PASS] 30-day projection verified: Balance=$1420, Reserved=$950, Safe Discretionary=$270")
    print(f"   [PASS] Detected {len(leaks)} subscription leaks totaling ${sum(l.annual_cost for l in leaks):.2f}/yr")
    print(f"   [PASS] Safe date for $850 item correctly identified as: {safe_date}")


def test_wise_score():
    print("[2/5] Testing WiseScore Calculation...")
    today = date.today()
    events = [
        FinancialEvent("rent", "expense", "Rent", 600.0, "outflow", today + timedelta(days=3), is_essential=True, is_subscription=False),
        FinancialEvent("salary", "income", "Salary", 1500.0, "inflow", today + timedelta(days=7), is_essential=False, is_subscription=False, confidence=0.95),
        FinancialEvent("spotify", "subscription", "Spotify", 9.99, "outflow", today + timedelta(days=5), is_essential=False, is_subscription=True, recurrence_days=30),
    ]

    model = CashflowModel(1200.0, 200.0, events)
    model.build()
    result = compute_wise_score(model)

    assert 0 <= result.score <= 100, f"Score out of range: {result.score}"
    assert result.grade in ["A+", "A", "B", "C", "D", "F"], f"Invalid grade: {result.grade}"
    assert len(result.insights) > 0, "Expected insights to be populated"

    print(f"   [PASS] WiseScore: {result.score}/100 (Grade: {result.grade})")
    print(f"   [PASS] Liquidity ratio: {result.liquidity_ratio * 100:.1f}%, Risk days: {result.overdraft_risk_days}")
    for insight in result.insights:
        print(f"     * {insight}")


def test_merchant_agent_a2a():
    print("[3/5] Testing Merchant Agent (A2A Negotiation)...")
    merchant = MerchantAgent(merchant_name="ElectroWorld Store", max_discount_pct=8.0, cost_floor_pct=0.70)

    # Offer 1: 5% discount (acceptable <= 8%)
    offer_good = NegotiationRequest(
        buyer_agent_id="buyer-001",
        product_name="Noise Cancelling Headphones",
        list_price=300.0,
        currency="USD",
        buyer_budget=285.0,
        proposed_discount_pct=5.0,
        allow_installments=True
    )
    res_good = merchant.negotiate(offer_good)
    assert res_good.accepted is True, "Expected 5% discount to be accepted"
    assert res_good.final_price is not None and res_good.final_price <= 285.0
    print(f"   [PASS] 5% discount offer accepted: ${offer_good.list_price} -> ${res_good.final_price}")

    # Offer 2: 15% discount (too steep > 8% -> merchant counters with 2-part installment plan)
    offer_steep = NegotiationRequest(
        buyer_agent_id="buyer-001",
        product_name="Gaming Monitor",
        list_price=400.0,
        currency="USD",
        buyer_budget=340.0,
        proposed_discount_pct=15.0,
        allow_installments=True
    )
    res_steep = merchant.negotiate(offer_steep)
    assert res_steep.accepted is False
    assert res_steep.counter_type == "counter_installment"
    assert len(res_steep.installment_plan) == 2
    print(f"   [PASS] 15% discount countered with 2-part installment: {res_steep.merchant_message}")


def test_buyer_agent_decisions():
    print("[4/5] Testing Buyer Agent Decisions & Autonomy Ladder...")
    today = date.today()
    events = [
        FinancialEvent("rent", "expense", "Rent", 800.0, "outflow", today + timedelta(days=4), is_essential=True, is_subscription=False),
        FinancialEvent("salary", "income", "Salary", 2000.0, "inflow", today + timedelta(days=10), is_essential=False, is_subscription=False, confidence=0.95),
    ]
    model = CashflowModel(1420.0, 200.0, events)
    model.build()
    # Safe today is: 1420 - 800 - 200 = 420.

    paypal_dummy = PayPalSandboxClient(client_id="dummy", client_secret="dummy")
    buyer = BuyerAgent(
        cashflow_model=model,
        paypal_client=paypal_dummy,
        autonomy_level=AutonomyLevel.ADVISE,
    )

    # Case A: Affordable Now (Item $150 <= $420)
    req_a = PurchaseRequest(product_name="Mechanical Keyboard", amount=150.0)
    dec_a = buyer.evaluate(req_a)
    assert dec_a.affordability_status == "affordable_now"
    assert dec_a.recommended_action == "full_payment"
    print(f"   [PASS] Case A ($150): {dec_a.affordability_status} -> {dec_a.recommended_action}")

    # Case B: Affordable with Plan -> Pay in 4 ($850 total -> $212.50/bi-weekly <= $420 safe today)
    req_b = PurchaseRequest(product_name="Dell UltraSharp Monitor", amount=850.0)
    dec_b = buyer.evaluate(req_b)
    assert dec_b.affordability_status == "affordable_with_plan"
    assert dec_b.recommended_action == "pay_in_4"
    assert len(dec_b.payment_plan) == 4
    print(f"   [PASS] Case B ($850): {dec_b.affordability_status} -> {dec_b.recommended_action} (4x ${dec_b.payment_plan[0]['amount']})")

    # Case C: Expensive Item -> Smart Wait ($2,000 total -> installment $500 > $420 safe today, waits for salary)
    req_c = PurchaseRequest(product_name="MacBook Pro", amount=2000.0)
    dec_c = buyer.evaluate(req_c)
    assert dec_c.affordability_status == "affordable_later"
    assert dec_c.recommended_action == "smart_wait"
    assert dec_c.earliest_safe_date == today + timedelta(days=10)
    print(f"   [PASS] Case C ($2,000): {dec_c.affordability_status} -> {dec_c.recommended_action} on {dec_c.earliest_safe_date}")

    # Case D: "Explain My No" content validation
    assert len(dec_c.explain_my_no) > 0
    print(f"   [PASS] 'Explain My No' sample: \"{dec_c.explain_my_no[:85]}...\"")


def test_paypal_client_structure():
    print("[5/5] Testing PayPal Sandbox Client Module Structure...")
    client = PayPalSandboxClient(client_id="sandbox_test_id", client_secret="sandbox_test_secret")
    assert hasattr(client, "create_order")
    assert hasattr(client, "capture_order")
    assert hasattr(client, "void_authorization")
    assert hasattr(client, "create_pay_in_4_order")
    assert hasattr(client, "cancel_subscription")
    assert hasattr(client, "create_payout")
    print("   [PASS] PayPal Sandbox SDK methods verified: Orders v2, Pay Later, Subscriptions, Payouts, Void")


def main():
    print("================================================================")
    print("         WISEPAYER ENGINE VERIFICATION & INTEGRATION SUITE      ")
    print("================================================================")
    try:
        test_cashflow_and_leaks()
        test_wise_score()
        test_merchant_agent_a2a()
        test_buyer_agent_decisions()
        test_paypal_client_structure()
        print("\n================================================================")
        print(">> ALL TESTS PASSED! ALL ENGINE COMPONENTS READY.")
        print("================================================================")
    except AssertionError as e:
        print(f"\n[FAIL] Test assertion failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n[FAIL] Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
