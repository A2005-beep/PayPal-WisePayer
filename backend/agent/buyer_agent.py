"""
WisePayer Buyer Agent
An LLM-powered agent with tools for cashflow analysis, PayPal transacting,
and the A2A merchant negotiation protocol.

Autonomy Levels:
  ADVISE  (0) – returns recommendation, user must confirm
  BOUNDED (1) – auto-executes if amount <= user threshold AND cashflow is safe
  GUARDIAN(2) – auto-executes with 30-min Emergency Rollback Window
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import IntEnum
from typing import Any, Optional

from ..engine.cashflow_model import CashflowModel
from ..engine.wise_score import compute_wise_score
from ..paypal.sandbox_client import PayPalSandboxClient

logger = logging.getLogger(__name__)

try:
    import google.generativeai as genai
    _GENAI_AVAILABLE = True
except ImportError:
    _GENAI_AVAILABLE = False
    logger.warning("google-generativeai not installed. LLM features will use rule-based fallback.")


class AutonomyLevel(IntEnum):
    ADVISE = 0
    BOUNDED = 1
    GUARDIAN = 2


@dataclass
class PurchaseRequest:
    product_name: str
    amount: float
    currency: str = "USD"
    product_url: Optional[str] = None
    merchant_agent_url: Optional[str] = None   # endpoint for A2A negotiation
    desired_date: Optional[date] = None


@dataclass
class AgentDecision:
    """Full decision output from the Buyer Agent."""
    affordability_status: str          # affordable_now | affordable_with_plan | affordable_later | not_affordable
    recommended_action: str            # full_payment | pay_in_4 | smart_wait | not_recommended
    safe_to_pay_today: float
    earliest_safe_date: Optional[date]
    negotiated_amount: Optional[float]  # set if A2A negotiation succeeded
    payment_plan: list[dict]           # [{date, amount}]
    explain_my_no: str                 # human-readable reason card text
    wise_score: int
    autonomy_level: AutonomyLevel
    paypal_order_id: Optional[str] = None
    rollback_deadline: Optional[datetime] = None
    metadata: dict[str, Any] = field(default_factory=dict)


class BuyerAgent:
    """
    Orchestrates the full WisePayer decision loop:
    1. Check cashflow model for safe liquidity
    2. (Optional) Negotiate with Merchant Agent via A2A protocol
    3. Select optimal payment strategy
    4. Execute via PayPal Sandbox (if autonomy level permits)
    5. Return structured AgentDecision
    """

    BOUNDED_AUTO_LIMIT_DEFAULT = 50.0   # USD

    def __init__(
        self,
        cashflow_model: CashflowModel,
        paypal_client: PayPalSandboxClient,
        autonomy_level: AutonomyLevel = AutonomyLevel.ADVISE,
        bounded_limit: float = BOUNDED_AUTO_LIMIT_DEFAULT,
        llm_model: str = "gemini-2.0-flash",
    ):
        self.model = cashflow_model
        self.paypal = paypal_client
        self.autonomy = autonomy_level
        self.bounded_limit = bounded_limit
        self.llm_model_name = llm_model

        if _GENAI_AVAILABLE:
            api_key = os.environ.get("GEMINI_API_KEY", "")
            if api_key:
                genai.configure(api_key=api_key)
                self._llm = genai.GenerativeModel(llm_model)
            else:
                self._llm = None
                logger.warning("GEMINI_API_KEY not set. Using rule-based fallback.")
        else:
            self._llm = None

    # ─────────────────────────────────────────── main entry point ────────────
    def evaluate(self, request: PurchaseRequest) -> AgentDecision:
        """Main entry: evaluate a purchase request and optionally execute it."""
        if not self.model._built:
            self.model.build()

        safe_today = self.model.safe_discretionary_today()
        earliest = self.model.earliest_safe_date(request.amount)
        wise = compute_wise_score(self.model)

        # ── Step 1: Determine affordability
        if safe_today >= request.amount:
            status = "affordable_now"
            action = "full_payment"
        elif safe_today > 0 and self._pay_in_4_safe(request.amount):
            status = "affordable_with_plan"
            action = "pay_in_4"
        elif earliest and earliest <= (request.desired_date or date.today() + timedelta(days=30)):
            status = "affordable_later"
            action = "smart_wait"
        else:
            status = "not_affordable"
            action = "not_recommended"

        # ── Step 2: A2A negotiation (if merchant endpoint provided)
        negotiated_amount = None
        if request.merchant_agent_url and action in ("not_recommended", "smart_wait"):
            negotiated_amount = self._negotiate_with_merchant(request, safe_today)
            if negotiated_amount and negotiated_amount <= safe_today:
                status = "affordable_now"
                action = "full_payment"

        final_amount = negotiated_amount or request.amount

        # ── Step 3: Build payment plan
        plan = self._build_payment_plan(action, final_amount, safe_today, earliest)

        # ── Step 4: Generate "Explain My No" card
        explain = self._generate_explanation(request, status, action, safe_today, earliest)

        # ── Step 5: Execute (if autonomy permits)
        order_id = None
        rollback_deadline = None
        if self._should_auto_execute(action, final_amount):
            order_id, rollback_deadline = self._execute_payment(action, final_amount, request)

        return AgentDecision(
            affordability_status=status,
            recommended_action=action,
            safe_to_pay_today=safe_today,
            earliest_safe_date=earliest,
            negotiated_amount=negotiated_amount,
            payment_plan=plan,
            explain_my_no=explain,
            wise_score=wise.score,
            autonomy_level=self.autonomy,
            paypal_order_id=order_id,
            rollback_deadline=rollback_deadline,
        )

    # ─────────────────────────────────────────── payment strategy ────────────
    def _pay_in_4_safe(self, amount: float) -> bool:
        """Check if Pay in 4 installments keep cashflow safe across 6 weeks."""
        installment = amount / 4
        dates_to_check = [
            date.today(),
            date.today() + timedelta(weeks=2),
            date.today() + timedelta(weeks=4),
            date.today() + timedelta(weeks=6),
        ]
        for d in dates_to_check:
            snap = self.model.balance_on(d)
            if snap and snap.available_discretionary < installment:
                return False
        return True

    def _build_payment_plan(
        self,
        action: str,
        amount: float,
        safe_today: float,
        earliest: Optional[date],
    ) -> list[dict]:
        today = date.today()
        if action == "full_payment":
            return [{"date": today.isoformat(), "amount": round(amount, 2)}]
        if action == "pay_in_4":
            installment = round(amount / 4, 2)
            return [
                {"date": (today + timedelta(weeks=i * 2)).isoformat(), "amount": installment}
                for i in range(4)
            ]
        if action == "smart_wait" and earliest:
            return [{"date": earliest.isoformat(), "amount": round(amount, 2)}]
        return []

    # ─────────────────────────────────────────── explanation card ────────────
    def _generate_explanation(
        self,
        request: PurchaseRequest,
        status: str,
        action: str,
        safe_today: float,
        earliest: Optional[date],
    ) -> str:
        snap = self.model.today_snapshot()
        # Try LLM-generated explanation first
        if self._llm:
            return self._llm_explanation(request, status, action, safe_today, earliest, snap)
        # Rule-based fallback
        reserved = snap.reserved_essential
        balance = snap.projected_balance
        min_bal = self.model.minimum_balance

        if status == "affordable_now":
            return (
                f"✅ Safe to purchase. Your balance is ${balance:,.2f}, "
                f"with ${reserved:,.2f} reserved for upcoming bills. "
                f"Available discretionary: ${safe_today:,.2f} — "
                f"comfortably covers ${request.amount:,.2f}."
            )
        if action == "pay_in_4":
            installment = request.amount / 4
            return (
                f"💡 Full payment would strain your buffer. However, "
                f"Pay in 4 (${installment:,.2f} × 4, bi-weekly) keeps your balance "
                f"above the ${min_bal:,.2f} minimum throughout. Recommended."
            )
        if action == "smart_wait":
            return (
                f"⏳ Not safe to pay ${request.amount:,.2f} today. "
                f"Your available discretionary is only ${safe_today:,.2f} "
                f"(${reserved:,.2f} reserved for upcoming bills). "
                f"Earliest safe date: {earliest}. WisePayer will auto-execute on that date."
            )
        return (
            f"🛑 Purchase of ${request.amount:,.2f} is not recommended. "
            f"Even with spending changes, the full amount cannot be safely covered "
            f"within 30 days. Current safe spending limit: ${safe_today:,.2f}."
        )

    def _llm_explanation(self, request, status, action, safe_today, earliest, snap) -> str:
        prompt = f"""You are WisePayer, an AI financial guardian. Generate a clear, friendly 2-3 sentence 
"Explain My No" card for a checkout decision. Be concise and empathetic.

Purchase: {request.product_name} (${request.amount:.2f})
Decision: {status} → {action}
Current balance: ${snap.projected_balance:,.2f}
Reserved for bills: ${snap.reserved_essential:,.2f}
Available discretionary: ${safe_today:,.2f}
Earliest safe date: {earliest}

Output only the explanation text, no JSON or markdown."""
        try:
            response = self._llm.generate_content(prompt)
            return response.text.strip()
        except Exception as e:
            logger.warning("LLM explanation failed: %s. Using fallback.", e)
            return self._generate_explanation.__wrapped__(self, request, status, action, safe_today, earliest)

    # ──────────────────────────────────────── A2A merchant negotiation ───────
    def _negotiate_with_merchant(
        self, request: PurchaseRequest, safe_budget: float
    ) -> Optional[float]:
        """
        Simulate A2A negotiation with merchant agent.
        In production: POST to request.merchant_agent_url.
        Here: mock protocol for demo purposes.
        """
        if not request.merchant_agent_url:
            return None

        shortfall = request.amount - safe_budget
        if shortfall <= 0:
            return request.amount

        # Buyer agent proposes: "can you match my budget?"
        buyer_offer = safe_budget
        discount_pct = (shortfall / request.amount) * 100

        logger.info(
            "[A2A] Buyer Agent → Merchant: Offering $%.2f (%.1f%% discount requested)",
            buyer_offer,
            discount_pct,
        )

        # Merchant agent logic (mock): Accept up to 8% discount
        if discount_pct <= 8.0:
            agreed_price = round(request.amount * (1 - discount_pct / 100), 2)
            logger.info("[A2A] Merchant Agent → Buyer: Accepted. Price: $%.2f", agreed_price)
            return agreed_price
        else:
            # Counter-offer: merchant splits to installments instead
            logger.info("[A2A] Merchant Agent → Buyer: Discount too high. Offering installment plan.")
            return None

    # ──────────────────────────────────────────────── auto-execution ─────────
    def _should_auto_execute(self, action: str, amount: float) -> bool:
        if self.autonomy == AutonomyLevel.ADVISE:
            return False
        if self.autonomy == AutonomyLevel.BOUNDED:
            return action == "full_payment" and amount <= self.bounded_limit
        if self.autonomy == AutonomyLevel.GUARDIAN:
            return action in ("full_payment", "pay_in_4")
        return False

    def _execute_payment(
        self, action: str, amount: float, request: PurchaseRequest
    ) -> tuple[Optional[str], Optional[datetime]]:
        try:
            if action == "pay_in_4":
                result = self.paypal.create_pay_in_4_order(
                    total_amount=amount,
                    currency=request.currency,
                    description=request.product_name,
                )
            else:
                result = self.paypal.create_order(
                    amount=amount,
                    currency=request.currency,
                    description=request.product_name,
                )
            order_id = result.get("order_id")
            rollback = datetime.now() + timedelta(minutes=30)
            logger.info("Auto-executed order %s. Rollback window until %s", order_id, rollback)
            return order_id, rollback
        except Exception as exc:
            logger.error("Auto-execution failed: %s", exc)
            return None, None
