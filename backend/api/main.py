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
    allow_origins=["*"],      # Tighten to actual frontend domain in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Singleton PayPal client (initialized from env vars)
_paypal_client: Optional[PayPalSandboxClient] = None

# In-memory smart-wait holds store (production: use Redis / DB)
_smart_wait_holds: list[dict[str, Any]] = []


def get_paypal() -> PayPalSandboxClient:
    global _paypal_client
    if _paypal_client is None:
        _paypal_client = PayPalSandboxClient(
            client_id=os.environ.get("PAYPAL_CLIENT_ID", ""),
            client_secret=os.environ.get("PAYPAL_CLIENT_SECRET", ""),
        )
    return _paypal_client


# ──────────────────────────────────────────── Pydantic schemas ────────────────

class EvaluateRequest(BaseModel):
    user_id: str
    product_name: str
    amount: float = Field(gt=0)
    currency: str = "USD"
    product_url: Optional[str] = None
    merchant_agent_url: Optional[str] = None
    desired_date: Optional[str] = None   # ISO date string
    autonomy_level: int = Field(0, ge=0, le=2)
    bounded_limit: float = 50.0
    # Inline financial profile (real app would fetch from DB)
    current_balance: float = Field(gt=0)
    minimum_balance: float = 0.0
    events: list[dict[str, Any]] = Field(default_factory=list)


class MerchantNegotiateRequest(BaseModel):
    buyer_agent_id: str
    product_name: str
    list_price: float
    currency: str = "USD"
    buyer_budget: float
    proposed_discount_pct: float
    allow_installments: bool = True


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


@app.post("/evaluate")
async def evaluate_purchase(req: EvaluateRequest, background: BackgroundTasks):
    """
    Main evaluation endpoint. Runs the Buyer Agent to assess affordability,
    optionally execute, and return the full AgentDecision.
    """
    events = _parse_events(req.events)
    cashflow = CashflowModel(
        current_balance=req.current_balance,
        minimum_balance=req.minimum_balance,
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
        bounded_limit=req.bounded_limit,
    )
    decision = agent.evaluate(purchase)

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
        "rollback_deadline": decision.rollback_deadline.isoformat() if decision.rollback_deadline else None,
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
async def get_cashflow(user_id: str, balance: float = 1000.0, min_balance: float = 200.0):
    """
    Return 30-day cashflow snapshots for AG Grid visualization.
    In production, user profile and events are fetched from a database.
    Here we return mock data if no events are provided.
    """
    events = _generate_demo_events(balance)
    model = CashflowModel(
        current_balance=balance,
        minimum_balance=min_balance,
        events=events,
    )
    model.build()
    return {
        "user_id": user_id,
        "currency": model.home_currency,
        "current_balance": balance,
        "minimum_balance": min_balance,
        "cashflow_rows": model.to_dict_list(),
        "summary": {
            "safe_today": model.safe_discretionary_today(),
            "forecast_days": model.FORECAST_DAYS,
        },
    }


@app.get("/wise-score/{user_id}")
async def get_wise_score(user_id: str, balance: float = 1000.0, min_balance: float = 200.0):
    events = _generate_demo_events(balance)
    model = CashflowModel(current_balance=balance, minimum_balance=min_balance, events=events)
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
async def get_subscription_leaks(user_id: str, balance: float = 1000.0, min_balance: float = 200.0):
    events = _generate_demo_events(balance)
    model = CashflowModel(current_balance=balance, minimum_balance=min_balance, events=events)
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
    return {"user_id": user_id, "leaks": leaks, "total_annual_waste": sum(l["annual_cost"] for l in leaks)}


@app.post("/subscription/{subscription_id}/cancel")
async def cancel_subscription(subscription_id: str):
    """1-tap cancel a PayPal subscription via API."""
    try:
        success = get_paypal().cancel_subscription(subscription_id)
        return {"cancelled": success, "subscription_id": subscription_id}
    except PayPalAPIError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/paypal/webhook")
async def paypal_webhook(event: WebhookEvent, background: BackgroundTasks):
    """
    Receive PayPal webhook events. Key events:
    - PAYMENT.SALE.COMPLETED → trigger smart-wait hold release
    - BILLING.SUBSCRIPTION.CANCELLED → update subscription ledger
    """
    logger.info("Webhook received: %s", event.event_type)
    if event.event_type == "PAYMENT.SALE.COMPLETED":
        background.add_task(_process_payment_completed, event)
    elif event.event_type == "BILLING.SUBSCRIPTION.CANCELLED":
        background.add_task(_process_subscription_cancelled, event)
    return {"received": True}


@app.get("/smart-wait-holds")
async def get_smart_wait_holds():
    """Return all pending smart-wait holds for Bryntum timeline visualization."""
    return {"holds": _smart_wait_holds}


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
    """Demo events for the cashflow visualization endpoint."""
    from datetime import timedelta
    today = date.today()
    return [
        FinancialEvent("ev1", "expense", "Rent", balance * 0.35, "outflow", today + timedelta(days=5),
                       is_essential=True, is_subscription=False),
        FinancialEvent("ev2", "expense", "Car Insurance", balance * 0.08, "outflow", today + timedelta(days=3),
                       is_essential=True, is_subscription=False),
        FinancialEvent("ev3", "income", "Salary", balance * 0.8, "inflow", today + timedelta(days=10),
                       is_essential=False, is_subscription=False, confidence=0.95),
        FinancialEvent("ev4", "subscription", "Netflix", 15.99, "outflow", today + timedelta(days=7),
                       is_essential=False, is_subscription=True, recurrence_days=30),
        FinancialEvent("ev5", "subscription", "Spotify", 9.99, "outflow", today + timedelta(days=12),
                       is_essential=False, is_subscription=True, recurrence_days=30),
        FinancialEvent("ev6", "subscription", "Gym Membership", 45.0, "outflow", today + timedelta(days=1),
                       is_essential=False, is_subscription=True, recurrence_days=30),
        FinancialEvent("ev7", "expense", "Groceries", balance * 0.05, "outflow", today + timedelta(days=2),
                       is_essential=True, is_subscription=False),
    ]


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
