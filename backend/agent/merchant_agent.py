"""
WisePayer Merchant Agent (A2A Commerce Counter-Party)
Simulates a merchant-side AI agent that can:
  - Respond to buyer agent price negotiation requests
  - Accept discount or installment proposals
  - Counter-offer with alternative payment structures
  - Settle final payment via PayPal on agreement

This is exposed as a FastAPI endpoint (/a2a/merchant/negotiate)
so the Buyer Agent can POST negotiation requests to it.
"""
from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class NegotiationRequest:
    buyer_agent_id: str
    product_name: str
    list_price: float
    currency: str
    buyer_budget: float
    proposed_discount_pct: float
    allow_installments: bool = True


@dataclass
class NegotiationResponse:
    accepted: bool
    counter_type: str            # accepted | counter_discount | counter_installment | rejected
    final_price: Optional[float]
    installment_plan: Optional[list[dict]]  # [{due_date, amount}]
    merchant_message: str
    margin_protected: bool       # True if merchant stays above cost floor


class MerchantAgent:
    """
    Merchant-side AI agent with configurable margin floor and negotiation policy.
    Max discount: 8% of list price (configurable).
    """

    def __init__(
        self,
        merchant_name: str = "Demo Merchant",
        max_discount_pct: float = 8.0,
        cost_floor_pct: float = 0.70,  # cost is 70% of list price
    ):
        self.merchant_name = merchant_name
        self.max_discount_pct = max_discount_pct
        self.cost_floor_pct = cost_floor_pct

    def negotiate(self, req: NegotiationRequest) -> NegotiationResponse:
        """
        Evaluate buyer agent's offer and respond with accept / counter / reject.
        """
        cost_floor = req.list_price * self.cost_floor_pct
        requested_price = req.list_price * (1 - req.proposed_discount_pct / 100)

        logger.info(
            "[MerchantAgent] Received offer: %.1f%% discount on %s ($%.2f → $%.2f)",
            req.proposed_discount_pct,
            req.product_name,
            req.list_price,
            requested_price,
        )

        # ── Case 1: Within acceptable discount range
        if req.proposed_discount_pct <= self.max_discount_pct and requested_price >= cost_floor:
            # Small random variance to make it feel like real negotiation
            final = round(requested_price * random.uniform(0.995, 1.0), 2)
            return NegotiationResponse(
                accepted=True,
                counter_type="accepted",
                final_price=final,
                installment_plan=None,
                merchant_message=(
                    f"✅ {self.merchant_name} accepts your offer. "
                    f"Final price: ${final:.2f} ({req.proposed_discount_pct:.1f}% off). "
                    f"Ready for PayPal checkout."
                ),
                margin_protected=True,
            )

        # ── Case 2: Discount too large — counter with installment offer
        if req.allow_installments and req.proposed_discount_pct > self.max_discount_pct:
            installment_amount = round(req.list_price / 2, 2)
            plan = [
                {"due_date": "today", "amount": installment_amount},
                {"due_date": "+30 days", "amount": installment_amount},
            ]
            return NegotiationResponse(
                accepted=False,
                counter_type="counter_installment",
                final_price=req.list_price,
                installment_plan=plan,
                merchant_message=(
                    f"⚡ {self.merchant_name} cannot match that discount, but offers 2-part payment: "
                    f"${installment_amount:.2f} today + ${installment_amount:.2f} in 30 days. "
                    f"No interest, no fees."
                ),
                margin_protected=True,
            )

        # ── Case 3: Price would be below cost floor — reject
        return NegotiationResponse(
            accepted=False,
            counter_type="rejected",
            final_price=None,
            installment_plan=None,
            merchant_message=(
                f"🚫 {self.merchant_name} is unable to match this offer. "
                f"Best available price: ${req.list_price * (1 - self.max_discount_pct / 100):.2f} "
                f"({self.max_discount_pct:.0f}% off)."
            ),
            margin_protected=False,
        )
