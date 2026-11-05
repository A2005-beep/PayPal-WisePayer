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

try:
    from ..engine.cashflow_model import CashflowModel
    from ..engine.wise_score import compute_wise_score
    from ..paypal.sandbox_client import PayPalSandboxClient
except (ImportError, ValueError):
    from engine.cashflow_model import CashflowModel
    from engine.wise_score import compute_wise_score
    from paypal.sandbox_client import PayPalSandboxClient

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
    paypal_approval_url: Optional[str] = None
    rollback_deadline: Optional[datetime] = None
    counterfactuals: list[dict] = field(default_factory=list)
    negotiation_details: Optional[dict[str, Any]] = None
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
        negotiation_details = None
        if request.merchant_agent_url:
            negotiation_details = self._negotiate_with_merchant_detailed(request, safe_today)
            if negotiation_details.get("accepted"):
                final_price = negotiation_details.get("final_price")
                if final_price and final_price <= safe_today:
                    negotiated_amount = final_price
                    status = "affordable_now"
                    action = "full_payment"

        final_amount = negotiated_amount or request.amount

        # ── Step 3: Build payment plan
        plan = self._build_payment_plan(action, final_amount, safe_today, earliest)

        # ── Step 4: Generate counterfactual analysis
        counterfactuals = self._build_counterfactuals(request.amount, safe_today, earliest)

        # ── Step 5: Generate "Explain My No" card
        explain = self._generate_explanation(request, status, action, safe_today, earliest)

        # ── Step 6: Execute (if autonomy permits)
        order_id = None
        approval_url = None
        rollback_deadline = None
        if self._should_auto_execute(action, final_amount):
            order_id, approval_url, rollback_deadline = self._execute_payment(action, final_amount, request)

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
            paypal_approval_url=approval_url,
            rollback_deadline=rollback_deadline,
            counterfactuals=counterfactuals,
            negotiation_details=negotiation_details,
        )

    # ─────────────────────────────────────────── payment strategy ────────────
    def _pay_in_4_safe(self, amount: float) -> bool:
        """
        Check if Pay in 4 installments keep cashflow safe across 6 weeks.
        Verifies:
        1. First installment does not exceed safe discretionary liquidity today.
        2. Lowest projected daily balance before next income NEVER breaches minimum buffer.
        3. All bi-weekly installment dates have sufficient discretionary margin.
        """
        installment = amount / 4
        if installment > self.model.safe_discretionary_today():
            return False

        # Verify that paying installment today does NOT cause balance to breach minimum_balance on ANY day ahead
        # before the next major inflow
        for snap in self.model.snapshots[:14]:
            if (snap.projected_balance - installment) < self.model.minimum_balance:
                return False

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

    def _build_counterfactuals(
        self, amount: float, safe_today: float, earliest: Optional[date]
    ) -> list[dict]:
        """
        Side-by-side purchase scenario simulation:
        Option 1: Buy in Full Today
        Option 2: PayPal Pay in 4
        Option 3: Smart Wait (Post-Income Release)
        """
        # Option 1: Buy in Full Today
        lowest_bal_full = min(snap.projected_balance - amount for snap in self.model.snapshots[:14])
        is_safe_full = safe_today >= amount and lowest_bal_full >= self.model.minimum_balance

        # Option 2: Pay in 4
        installment = round(amount / 4, 2)
        lowest_bal_p4 = min(snap.projected_balance - installment for snap in self.model.snapshots[:14])
        is_safe_p4 = self._pay_in_4_safe(amount)

        # Option 3: Smart Wait
        wait_date_str = earliest.strftime('%b %d') if earliest else 'After Next Payday'
        lowest_bal_wait = min(snap.projected_balance for snap in self.model.snapshots)

        return [
            {
                "option": "Buy in Full Today",
                "upfront": amount,
                "lowest_projected_balance": round(lowest_bal_full, 2),
                "is_safe": is_safe_full,
                "status": "Safe & Approved" if is_safe_full else f"Breaches Buffer (${lowest_bal_full:.2f} < ${self.model.minimum_balance:.0f})",
                "risk_assessment": "Safe within discretionary liquidity" if is_safe_full else "Compromises upcoming essential bills",
            },
            {
                "option": "PayPal Pay in 4",
                "upfront": installment,
                "lowest_projected_balance": round(lowest_bal_p4, 2),
                "is_safe": is_safe_p4,
                "status": "Safe with Plan" if is_safe_p4 else f"Installment Breaches Buffer (${lowest_bal_p4:.2f})",
                "risk_assessment": "4 biweekly installments protect liquidity" if is_safe_p4 else "First payment creates cashflow shortfall before salary",
            },
            {
                "option": f"Smart Wait ({wait_date_str})",
                "upfront": 0.0,
                "lowest_projected_balance": round(lowest_bal_wait, 2),
                "is_safe": True,
                "status": "Guaranteed Safe",
                "risk_assessment": "Defers execution until verified salary arrival",
            },
        ]

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
        if self._llm:
            try:
                text = self._llm_explanation(request, status, action, safe_today, earliest, snap)
                if text:
                    return text
            except Exception as e:
                logger.warning("LLM explanation failed: %s. Falling back to rule-based engine.", e)
        return self._rule_based_explanation(request, status, action, safe_today, earliest, snap)

    def _rule_based_explanation(
        self,
        request: PurchaseRequest,
        status: str,
        action: str,
        safe_today: float,
        earliest: Optional[date],
        snap: Any,
    ) -> str:
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
        response = self._llm.generate_content(prompt)
        return response.text.strip() if response and response.text else ""

    # ──────────────────────────────────────── A2A merchant negotiation ───────
    def _negotiate_with_merchant_detailed(
        self, request: PurchaseRequest, safe_budget: float
    ) -> dict[str, Any]:
        """
        Structured A2A negotiation protocol:
        Buyer Agent submits budget constraint and requested discount.
        Merchant Agent responds with acceptance, counter-offer, or installment terms.
        """
        shortfall = max(0.0, request.amount - safe_budget)
        discount_pct = (shortfall / request.amount) * 100 if shortfall > 0 else 5.0

        try:
            try:
                from ..agent.merchant_agent import MerchantAgent, NegotiationRequest
            except (ImportError, ValueError):
                from agent.merchant_agent import MerchantAgent, NegotiationRequest

            merchant = MerchantAgent(merchant_name="ElectroWorld Partner Store", max_discount_pct=10.0)
            res = merchant.negotiate(NegotiationRequest(
                buyer_agent_id="wisepayer-buyer-agent",
                product_name=request.product_name,
                list_price=request.amount,
                currency=request.currency,
                buyer_budget=safe_budget,
                proposed_discount_pct=discount_pct,
                allow_installments=True,
            ))

            is_accepted = res.accepted and (res.final_price <= safe_budget or safe_budget >= request.amount)
            return {
                "attempted": True,
                "accepted": is_accepted,
                "counter_type": res.counter_type,
                "merchant_name": "ElectroWorld Partner Store",
                "buyer_budget_constraint": round(safe_budget, 2),
                "list_price": request.amount,
                "discount_requested_pct": round(discount_pct, 1),
                "final_price": res.final_price,
                "installment_plan": res.installment_plan,
                "merchant_message": res.merchant_message,
                "ai_agent_rationale": (
                    f"Buyer Agent set safe ceiling at ${safe_budget:.2f}. "
                    f"Merchant Agent responded with {res.counter_type}: {res.merchant_message}"
                ),
            }
        except Exception as exc:
            logger.warning("[A2A] Negotiation error: %s", exc)
            return {
                "attempted": True,
                "accepted": False,
                "counter_type": "error",
                "merchant_message": str(exc),
                "ai_agent_rationale": f"Negotiation protocol offline: {exc}",
            }

    def _negotiate_with_merchant(
        self, request: PurchaseRequest, safe_budget: float
    ) -> Optional[float]:
        details = self._negotiate_with_merchant_detailed(request, safe_budget)
        if details.get("accepted"):
            return details.get("final_price")
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
    ) -> tuple[Optional[str], Optional[str], Optional[datetime]]:
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
            approval_url = result.get("approval_url")
            rollback = datetime.now() + timedelta(minutes=30)
            logger.info("Auto-executed order %s. Rollback window until %s", order_id, rollback)
            return order_id, approval_url, rollback
        except Exception as exc:
            logger.error("Auto-execution failed: %s", exc)
            return None, None, None
