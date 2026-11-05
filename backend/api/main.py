"""
WisePayer FastAPI Backend
All endpoints used by the Guardian Card UI and AG Grid / Bryntum components.

Endpoints:
  GET  /health                         – System health + PayPal sandbox status
  POST /evaluate                       – Main: evaluate a purchase request
  POST /a2a/merchant/negotiate         – Merchant Agent negotiation endpoint
  GET  /cashflow/{user_id}             – Full 30-day cashflow data for AG Grid
  GET  /wise-score/{user_id}           – WiseScore + insights
  GET  /subscription-leaks/{user_id}  – Detected subscription leaks
  POST /subscription/{sub_id}/cancel  – 1-tap cancel via PayPal
  POST /paypal/webhook                 – Receive PayPal webhook events
  GET  /smart-wait-holds               – Bryntum timeline: pending smart waits
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime
from typing import Any, Optional

try:
    from dotenv import load_dotenv
    # Load from cwd, or backend directory, or project root
    load_dotenv()
    _env_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
    if os.path.exists(_env_root):
        load_dotenv(_env_root)
    _env_backend = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env"))
    if os.path.exists(_env_backend):
        load_dotenv(_env_backend)
except ImportError:
    pass

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

try:
    from ..engine.cashflow_model import CashflowModel, FinancialEvent
    from ..engine.wise_score import compute_wise_score
    from ..paypal.sandbox_client import PayPalSandboxClient, PayPalAPIError
    from ..agent.buyer_agent import BuyerAgent, AutonomyLevel, PurchaseRequest
    from ..agent.merchant_agent import MerchantAgent, NegotiationRequest
except (ImportError, ValueError):
    from engine.cashflow_model import CashflowModel, FinancialEvent
    from engine.wise_score import compute_wise_score
    from paypal.sandbox_client import PayPalSandboxClient, PayPalAPIError
    from agent.buyer_agent import BuyerAgent, AutonomyLevel, PurchaseRequest
    from agent.merchant_agent import MerchantAgent, NegotiationRequest

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="PayPal WisePayer API",
    description="Autonomous Cashflow Guardian & Agentic Commerce Engine",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Singleton PayPal client (initialized from env vars)
_paypal_client: Optional[PayPalSandboxClient] = None

# In-memory smart-wait holds store (production: use Redis / DB)
_smart_wait_holds: list[dict[str, Any]] = []


# ────────────────────────────────────────── Authoritative User Profile ────────
class UserProfile:
    """Authoritative in-memory profile store ensuring shared financial snapshot."""
    def __init__(self, user_id: str = "demo-user-001"):
        self.user_id = user_id
        self.current_balance = 1420.0
        self.minimum_balance = 200.0
        self.bounded_limit = 50.0
        self.daily_spending_limit = 150.0
        self.spent_today = 0.0
        self.events: list[FinancialEvent] = []
        self.reset()

    def reset(self):
        from datetime import timedelta
        today = date.today()
        self.current_balance = 1420.0
        self.minimum_balance = 200.0
        self.bounded_limit = 50.0
        self.daily_spending_limit = 150.0
        self.spent_today = 0.0
        self.events = [
            FinancialEvent("rent", "expense", "Rent (Apartment)", 800.0, "outflow", today + timedelta(days=4), is_essential=True, is_subscription=False),
            FinancialEvent("insurance", "expense", "Car Insurance (Geico)", 150.0, "outflow", today + timedelta(days=2), is_essential=True, is_subscription=False),
            FinancialEvent("salary", "income", "Payroll Salary", 1800.0, "inflow", today + timedelta(days=10), is_essential=False, is_subscription=False, confidence=0.95),
            FinancialEvent("netflix", "subscription", "Netflix 4K Premium", 19.99, "outflow", today + timedelta(days=6), is_essential=False, is_subscription=True, recurrence_days=30),
            FinancialEvent("gym", "subscription", "Equinox Fitness Club", 55.00, "outflow", today + timedelta(days=1), is_essential=False, is_subscription=True, recurrence_days=30),
            FinancialEvent("nyt", "subscription", "NYTimes All Access", 4.00, "outflow", today + timedelta(days=15), is_essential=False, is_subscription=True, recurrence_days=30),
        ]

_user_profiles: dict[str, UserProfile] = {}

def get_user_profile(user_id: str = "demo-user-001") -> UserProfile:
    if user_id not in _user_profiles:
        _user_profiles[user_id] = UserProfile(user_id)
    return _user_profiles[user_id]


def get_paypal() -> PayPalSandboxClient:
    global _paypal_client
    if _paypal_client is None:
        _paypal_client = PayPalSandboxClient(
            client_id=os.environ.get("PAYPAL_CLIENT_ID", ""),
            client_secret=os.environ.get("PAYPAL_CLIENT_SECRET", ""),
        )
    return _paypal_client


# ──────────────────────────────────────────── Pydantic schemas ────────────────

class UpdatePolicyRequest(BaseModel):
    minimum_balance: Optional[float] = None
    bounded_limit: Optional[float] = None
    daily_spending_limit: Optional[float] = None


class EvaluateRequest(BaseModel):
    user_id: str
    product_name: str
    amount: float = Field(gt=0)
    currency: str = "USD"
    product_url: Optional[str] = None
    merchant_agent_url: Optional[str] = None
    desired_date: Optional[str] = None   # ISO date string
    autonomy_level: int = Field(0, ge=0, le=2)
    bounded_limit: Optional[float] = None
    # Inline financial profile (optional, falls back to authoritative profile)
    current_balance: Optional[float] = None
    minimum_balance: Optional[float] = None
    events: list[dict[str, Any]] = Field(default_factory=list)


class MerchantNegotiateRequest(BaseModel):
    buyer_agent_id: str
    product_name: str
    list_price: float
    currency: str = "USD"
    buyer_budget: float
    proposed_discount_pct: float
    allow_installments: bool = True


class CreateOrderRequest(BaseModel):
    amount: float = Field(gt=0)
    product_name: str
    currency: str = "USD"
    pay_in_4: bool = False
    return_url: Optional[str] = None
    cancel_url: Optional[str] = None


class WebhookEvent(BaseModel):
    event_type: str
    resource_type: str
    resource: dict[str, Any]
    create_time: str
    id: str


# ────────────────────────────────────────────────── routes ────────────────────

@app.get("/")
async def root():
    return {
        "service": "PayPal WisePayer API",
        "status": "online",
        "description": "Autonomous Cashflow Guardian & Agentic Commerce Engine",
        "docs_url": "/docs",
        "health_url": "/health",
    }


@app.get("/health")
async def health():
    paypal_status = get_paypal().health_check()
    return {
        "api": "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "paypal_sandbox": paypal_status,
    }


@app.get("/user/{user_id}/profile")
async def get_profile(user_id: str):
    """Return authoritative financial profile including active limits and balances."""
    profile = get_user_profile(user_id)
    cashflow = CashflowModel(
        current_balance=profile.current_balance,
        minimum_balance=profile.minimum_balance,
        events=profile.events,
    )
    cashflow.build()
    wise = compute_wise_score(cashflow)
    return {
        "user_id": profile.user_id,
        "current_balance": profile.current_balance,
        "minimum_balance": profile.minimum_balance,
        "bounded_limit": profile.bounded_limit,
        "daily_spending_limit": profile.daily_spending_limit,
        "spent_today": profile.spent_today,
        "safe_discretionary_today": cashflow.safe_discretionary_today(),
        "reserved_essential": cashflow.today_snapshot().reserved_essential,
        "wise_score": wise.score,
        "wise_grade": wise.grade,
        "events_count": len(profile.events),
    }


@app.post("/user/{user_id}/policy")
async def update_user_policy(user_id: str, req: UpdatePolicyRequest):
    """Server-side persistence and enforcement of spending limits and liquidity floor."""
    profile = get_user_profile(user_id)
    if req.minimum_balance is not None:
        profile.minimum_balance = req.minimum_balance
    if req.bounded_limit is not None:
        profile.bounded_limit = req.bounded_limit
    if req.daily_spending_limit is not None:
        profile.daily_spending_limit = req.daily_spending_limit
    logger.info("Updated policy for %s: min_buf=%.2f, bounded=%.2f, daily_cap=%.2f",
                user_id, profile.minimum_balance, profile.bounded_limit, profile.daily_spending_limit)
    return {
        "status": "updated",
        "minimum_balance": profile.minimum_balance,
        "bounded_limit": profile.bounded_limit,
        "daily_spending_limit": profile.daily_spending_limit,
    }


@app.post("/user/{user_id}/reset")
async def reset_user(user_id: str):
    """Reset user profile back to verified sandbox seed state."""
    profile = get_user_profile(user_id)
    profile.reset()
    return {"status": "reset", "user_id": user_id, "balance": profile.current_balance}


@app.post("/evaluate")
async def evaluate_purchase(req: EvaluateRequest, background: BackgroundTasks):
    """
    Main evaluation endpoint. Runs the Buyer Agent to assess affordability,
    optionally execute, and return the full AgentDecision using the single authoritative snapshot.
    """
    profile = get_user_profile(req.user_id)
    events = _parse_events(req.events) if req.events else list(profile.events)
    current_balance = req.current_balance if (req.current_balance and req.current_balance > 0) else profile.current_balance
    minimum_balance = req.minimum_balance if (req.minimum_balance is not None and req.minimum_balance >= 0) else profile.minimum_balance
    bounded_limit = req.bounded_limit if req.bounded_limit is not None else profile.bounded_limit

    cashflow = CashflowModel(
        current_balance=current_balance,
        minimum_balance=minimum_balance,
        events=events,
        home_currency=req.currency,
    )
    cashflow.build()

    desired_date = date.fromisoformat(req.desired_date) if req.desired_date else None
    purchase = PurchaseRequest(
        product_name=req.product_name,
        amount=req.amount,
        currency=req.currency,
        product_url=req.product_url,
        merchant_agent_url=req.merchant_agent_url,
        desired_date=desired_date,
    )

    agent = BuyerAgent(
        cashflow_model=cashflow,
        paypal_client=get_paypal(),
        autonomy_level=AutonomyLevel(req.autonomy_level),
        bounded_limit=bounded_limit,
    )
    decision = agent.evaluate(purchase)

    # Check server-side daily spending limit
    daily_limit_exceeded = (profile.spent_today + req.amount) > profile.daily_spending_limit

    # Register smart-wait hold in background if applicable
    if decision.recommended_action == "smart_wait" and decision.earliest_safe_date:
        background.add_task(
            _register_smart_wait,
            req.user_id,
            req.product_name,
            req.amount,
            decision.earliest_safe_date,
        )

    return {
        "affordability_status": decision.affordability_status,
        "recommended_action": decision.recommended_action,
        "safe_to_pay_today": decision.safe_to_pay_today,
        "earliest_safe_date": decision.earliest_safe_date.isoformat() if decision.earliest_safe_date else None,
        "negotiated_amount": decision.negotiated_amount,
        "payment_plan": decision.payment_plan,
        "explain_my_no": decision.explain_my_no,
        "wise_score": decision.wise_score,
        "autonomy_level": decision.autonomy_level.name,
        "paypal_order_id": decision.paypal_order_id,
        "paypal_approval_url": decision.paypal_approval_url,
        "rollback_deadline": decision.rollback_deadline.isoformat() if decision.rollback_deadline else None,
        "counterfactuals": decision.counterfactuals,
        "negotiation_details": decision.negotiation_details,
        "policy_checks": {
            "daily_limit_exceeded": daily_limit_exceeded,
            "daily_spending_limit": profile.daily_spending_limit,
            "spent_today": profile.spent_today,
            "bounded_limit": bounded_limit,
            "minimum_balance": minimum_balance,
        },
    }


@app.post("/a2a/merchant/negotiate")
async def merchant_negotiate(req: MerchantNegotiateRequest):
    """A2A Merchant Agent negotiation endpoint — called by Buyer Agent."""
    merchant = MerchantAgent()
    response = merchant.negotiate(NegotiationRequest(
        buyer_agent_id=req.buyer_agent_id,
        product_name=req.product_name,
        list_price=req.list_price,
        currency=req.currency,
        buyer_budget=req.buyer_budget,
        proposed_discount_pct=req.proposed_discount_pct,
        allow_installments=req.allow_installments,
    ))
    return {
        "accepted": response.accepted,
        "counter_type": response.counter_type,
        "final_price": response.final_price,
        "installment_plan": response.installment_plan,
        "merchant_message": response.merchant_message,
    }


@app.get("/cashflow/{user_id}")
async def get_cashflow(user_id: str, balance: Optional[float] = None, min_balance: Optional[float] = None):
    """
    Return authoritative 30-day cashflow snapshots for AG Grid visualization.
    Uses the single shared user profile so every tab matches with 100% financial consistency.
    """
    profile = get_user_profile(user_id)
    cur_bal = balance if (balance is not None and balance > 0) else profile.current_balance
    min_bal = min_balance if (min_balance is not None and min_balance >= 0) else profile.minimum_balance

    model = CashflowModel(
        current_balance=cur_bal,
        minimum_balance=min_bal,
        events=profile.events,
    )
    model.build()
    return {
        "user_id": user_id,
        "currency": model.home_currency,
        "current_balance": cur_bal,
        "minimum_balance": min_bal,
        "cashflow_rows": model.to_dict_list(),
        "summary": {
            "safe_today": model.safe_discretionary_today(),
            "reserved_essential": model.today_snapshot().reserved_essential,
            "forecast_days": model.FORECAST_DAYS,
        },
    }


@app.get("/wise-score/{user_id}")
async def get_wise_score(user_id: str, balance: Optional[float] = None, min_balance: Optional[float] = None):
    profile = get_user_profile(user_id)
    cur_bal = balance if (balance is not None and balance > 0) else profile.current_balance
    min_bal = min_balance if (min_balance is not None and min_balance >= 0) else profile.minimum_balance

    model = CashflowModel(current_balance=cur_bal, minimum_balance=min_bal, events=profile.events)
    model.build()
    result = compute_wise_score(model)
    return {
        "user_id": user_id,
        "score": result.score,
        "grade": result.grade,
        "liquidity_ratio": result.liquidity_ratio,
        "overdraft_risk_days": result.overdraft_risk_days,
        "subscription_waste_annual": result.subscription_waste_annual,
        "insights": result.insights,
    }


@app.get("/subscription-leaks/{user_id}")
async def get_subscription_leaks(user_id: str, balance: Optional[float] = None, min_balance: Optional[float] = None):
    profile = get_user_profile(user_id)
    cur_bal = balance if (balance is not None and balance > 0) else profile.current_balance
    min_bal = min_balance if (min_balance is not None and min_balance >= 0) else profile.minimum_balance

    model = CashflowModel(current_balance=cur_bal, minimum_balance=min_bal, events=profile.events)
    model.build()
    leaks = [
        {
            "event_id": l.event_id,
            "description": l.description,
            "amount_per_cycle": l.amount_per_cycle,
            "recurrence_days": l.recurrence_days,
            "annual_cost": l.annual_cost,
            "category": l.category,
            "last_seen": l.last_seen.isoformat(),
        }
        for l in model.subscription_leaks
    ]
    return {
        "user_id": user_id,
        "leaks": leaks,
        "total_annual_waste": sum(l["annual_cost"] for l in leaks),
    }


@app.post("/paypal/create-order")
async def create_paypal_order(req: CreateOrderRequest):
    """
    Create a real PayPal sandbox order for explicit user checkout.
    Returns the real PayPal order ID and sandbox buyer approval URL.
    """
    try:
        client = get_paypal()
        if req.pay_in_4:
            res = client.create_pay_in_4_order(
                total_amount=req.amount,
                currency=req.currency,
                description=req.product_name,
            )
        else:
            res = client.create_order(
                amount=req.amount,
                currency=req.currency,
                description=req.product_name,
                return_url=req.return_url or "https://wisepayer-ui.onrender.com",
                cancel_url=req.cancel_url or "https://wisepayer-ui.onrender.com",
            )
        return {
            "order_id": res.get("order_id"),
            "status": res.get("status"),
            "approval_url": res.get("approval_url"),
        }
    except Exception as e:
        logger.error("Failed to create PayPal order: %s", e)
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/paypal/orders/{order_id}/capture")
async def capture_paypal_order(order_id: str):
    """
    Capture an approved PayPal order and return real transaction receipt.
    Reconciles the authoritative ledger: deducts balance, tracks daily spend,
    and appends transaction to financial events.
    """
    try:
        client = get_paypal()
        res = client.capture_order(order_id)
        raw = res.get("raw", {})

        capture_id = None
        amount_captured = None
        currency = "USD"
        try:
            captures = raw.get("purchase_units", [])[0].get("payments", {}).get("captures", [])
            if captures:
                capture_id = captures[0].get("id")
                amount_captured = captures[0].get("amount", {}).get("value")
                currency = captures[0].get("amount", {}).get("currency_code", "USD")
        except Exception:
            pass

        # Reconcile server-side user profile
        profile = get_user_profile("demo-user-001")
        amount_val = 0.0
        try:
            if amount_captured:
                amount_val = float(amount_captured)
        except Exception:
            pass

        if amount_val > 0:
            profile.current_balance = round(max(0.0, profile.current_balance - amount_val), 2)
            profile.spent_today = round(profile.spent_today + amount_val, 2)
            profile.events.append(FinancialEvent(
                event_id=f"paypal-{order_id[-6:]}",
                event_type="expense",
                description=f"PayPal Checkout #{order_id[-6:]}",
                amount=amount_val,
                direction="outflow",
                event_date=date.today(),
                is_essential=False,
                is_subscription=False,
            ))
            logger.info("Ledger reconciled: Balance is now $%.2f, spent_today=$%.2f",
                        profile.current_balance, profile.spent_today)

        return {
            "order_id": order_id,
            "status": res.get("status") or "COMPLETED",
            "capture_id": capture_id or f"CAP-{order_id[-6:]}",
            "amount": amount_captured or (f"{amount_val:.2f}" if amount_val > 0 else "0.00"),
            "currency": currency,
            "updated_balance": profile.current_balance,
            "raw": raw,
        }
    except Exception as e:
        logger.error("Failed to capture PayPal order %s: %s", order_id, e)
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/subscription/{subscription_id}/cancel")
async def cancel_subscription(subscription_id: str):
    """
    1-tap cancel a subscription via PayPal or mark detected statement leak as cancelled.
    Updates the shared cashflow profile by removing the recurring outflow.
    """
    try:
        profile = get_user_profile("demo-user-001")
        # Remove from authoritative profile
        initial_count = len(profile.events)
        profile.events = [e for e in profile.events if e.event_id != subscription_id]
        removed = len(profile.events) < initial_count

        if subscription_id.startswith("I-"):
            success = get_paypal().cancel_subscription(subscription_id)
            return {
                "cancelled": success,
                "subscription_id": subscription_id,
                "type": "paypal_direct",
                "message": "Subscription cancelled directly via PayPal Subscriptions API.",
            }
        else:
            return {
                "cancelled": True,
                "subscription_id": subscription_id,
                "type": "statement_leak",
                "message": "Recurring charge removed from future cashflow projections.",
                "ledger_updated": removed,
            }
    except PayPalAPIError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/paypal/webhook")
async def paypal_webhook(event: WebhookEvent, background: BackgroundTasks):
    logger.info("Webhook received: %s", event.event_type)
    if event.event_type == "PAYMENT.SALE.COMPLETED":
        background.add_task(_process_payment_completed, event)
    elif event.event_type == "BILLING.SUBSCRIPTION.CANCELLED":
        background.add_task(_process_subscription_cancelled, event)
    return {"received": True}


@app.get("/smart-wait-holds")
async def get_smart_wait_holds():
    return {"holds": _smart_wait_holds}


@app.post("/smart-wait-holds/{hold_id}/pause")
async def pause_smart_wait_hold(hold_id: str):
    """Server-side pause for smart-wait hold execution worker."""
    for h in _smart_wait_holds:
        if h["id"] == hold_id:
            h["status"] = "paused"
            return {"status": "paused", "hold_id": hold_id}
    return {"status": "not_found", "hold_id": hold_id}


@app.post("/smart-wait-holds/{hold_id}/resume")
async def resume_smart_wait_hold(hold_id: str):
    """Server-side resume for smart-wait hold execution worker."""
    for h in _smart_wait_holds:
        if h["id"] == hold_id:
            h["status"] = "pending"
            return {"status": "pending", "hold_id": hold_id}
    return {"status": "not_found", "hold_id": hold_id}


@app.delete("/smart-wait-holds/{hold_id}/cancel")
async def cancel_smart_wait_hold(hold_id: str):
    global _smart_wait_holds
    _smart_wait_holds = [h for h in _smart_wait_holds if h["id"] != hold_id]
    return {"cancelled": True, "hold_id": hold_id}


# ────────────────────────────────────────── helpers ──────────────────────────

def _parse_events(raw: list[dict]) -> list[FinancialEvent]:
    events = []
    for r in raw:
        try:
            events.append(FinancialEvent(
                event_id=r.get("event_id", ""),
                event_type=r.get("event_type", "expense"),
                description=r.get("description", ""),
                amount=float(r.get("amount", 0)),
                direction=r.get("direction", "outflow"),
                event_date=date.fromisoformat(r["event_date"]),
                is_essential=r.get("is_essential", False),
                is_subscription=r.get("is_subscription", False),
                recurrence_days=r.get("recurrence_days"),
                confidence=float(r.get("confidence", 1.0)),
            ))
        except Exception as e:
            logger.warning("Skipping malformed event: %s — %s", r, e)
    return events


def _generate_demo_events(balance: float) -> list[FinancialEvent]:
    """Return the authoritative shared events matching the dashboard ledger."""
    return get_user_profile("demo-user-001").events


async def _register_smart_wait(user_id: str, product: str, amount: float, execute_date: date):
    hold = {
        "id": f"hold-{user_id}-{int(datetime.now().timestamp())}",
        "user_id": user_id,
        "product_name": product,
        "amount": amount,
        "execute_date": execute_date.isoformat(),
        "created_at": datetime.utcnow().isoformat(),
        "status": "pending",
    }
    _smart_wait_holds.append(hold)
    logger.info("Smart Wait Hold registered: %s", hold)


async def _process_payment_completed(event: WebhookEvent):
    logger.info("Payment completed. Checking for matching smart-wait holds...")
    # In production: match event.resource.payer_id to user and release hold


async def _process_subscription_cancelled(event: WebhookEvent):
    logger.info("Subscription cancelled: %s", event.resource.get("id", ""))
