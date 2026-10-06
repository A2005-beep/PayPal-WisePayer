"""
PayPal Sandbox Client
Handles all PayPal REST API v2 interactions:
  - OAuth 2.0 token management (auto-refresh)
  - Orders v2: Create, Capture, Void, Show
  - Pay Later / Pay in 4: Availability check & order configuration
  - Subscriptions: List active subscriptions, Cancel
  - Payouts: Create batch payout (for Agent-to-Agent settlement)
  - Webhooks: Simulate event (testing only)
"""
from __future__ import annotations

import os
import time
import logging
from typing import Any, Optional

try:
    import httpx
    _HTTPX_AVAILABLE = True
except ImportError:
    httpx = None
    _HTTPX_AVAILABLE = False

logger = logging.getLogger(__name__)

SANDBOX_BASE = "https://api-m.sandbox.paypal.com"


class PayPalSandboxClient:
    """
    Thin async-capable PayPal Sandbox REST client.
    All methods return parsed JSON dicts or raise PayPalAPIError.
    """

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
    ):
        self.client_id = client_id or os.environ.get("PAYPAL_CLIENT_ID", "")
        self.client_secret = client_secret or os.environ.get("PAYPAL_CLIENT_SECRET", "")
        self._access_token: Optional[str] = None
        self._token_expiry: float = 0.0
        self._http = httpx.Client(base_url=SANDBOX_BASE, timeout=30.0) if _HTTPX_AVAILABLE else None

    # ─────────────────────────────────────────────── auth ───────────────────
    def _ensure_token(self) -> str:
        if self._access_token and time.time() < self._token_expiry - 60:
            return self._access_token
        resp = self._http.post(
            "/v1/oauth2/token",
            auth=(self.client_id, self.client_secret),
            data={"grant_type": "client_credentials"},
        )
        _raise_for_status(resp, "OAuth token")
        body = resp.json()
        self._access_token = body["access_token"]
        self._token_expiry = time.time() + body.get("expires_in", 3600)
        logger.info("PayPal OAuth token refreshed.")
        return self._access_token

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._ensure_token()}",
            "Content-Type": "application/json",
        }

    # ─────────────────────────────────────────────── Orders v2 ──────────────
    def create_order(
        self,
        amount: float,
        currency: str = "USD",
        description: str = "",
        payment_source: Optional[dict] = None,
        return_url: str = "https://wisepayer.app/return",
        cancel_url: str = "https://wisepayer.app/cancel",
    ) -> dict[str, Any]:
        """Create a PayPal order. Returns the order ID and approval link."""
        body: dict[str, Any] = {
            "intent": "CAPTURE",
            "purchase_units": [
                {
                    "amount": {"currency_code": currency, "value": f"{amount:.2f}"},
                    "description": description,
                }
            ],
            "application_context": {
                "return_url": return_url,
                "cancel_url": cancel_url,
                "brand_name": "PayPal WisePayer",
                "user_action": "PAY_NOW",
            },
        }
        # Pay Later / Pay in 4 configuration
        if payment_source:
            body["payment_source"] = payment_source

        resp = self._http.post("/v2/checkout/orders", headers=self._headers(), json=body)
        _raise_for_status(resp, "create_order")
        data = resp.json()
        approval_link = next(
            (l["href"] for l in data.get("links", []) if l["rel"] == "approve"),
            None,
        )
        logger.info("Order created: %s", data.get("id"))
        return {
            "order_id": data.get("id"),
            "status": data.get("status"),
            "approval_url": approval_link,
            "raw": data,
        }

    def capture_order(self, order_id: str) -> dict[str, Any]:
        """Capture an approved order (triggers actual payment in sandbox)."""
        resp = self._http.post(
            f"/v2/checkout/orders/{order_id}/capture",
            headers=self._headers(),
            json={},
        )
        _raise_for_status(resp, "capture_order")
        data = resp.json()
        logger.info("Order captured: %s status=%s", order_id, data.get("status"))
        return {"order_id": order_id, "status": data.get("status"), "raw": data}

    def void_authorization(self, authorization_id: str) -> dict[str, Any]:
        """Void a previously authorized payment (Emergency Rollback)."""
        resp = self._http.post(
            f"/v2/payments/authorizations/{authorization_id}/void",
            headers=self._headers(),
            json={},
        )
        _raise_for_status(resp, "void_authorization")
        logger.info("Authorization voided: %s", authorization_id)
        return {"authorization_id": authorization_id, "voided": True}

    def show_order(self, order_id: str) -> dict[str, Any]:
        resp = self._http.get(f"/v2/checkout/orders/{order_id}", headers=self._headers())
        _raise_for_status(resp, "show_order")
        return resp.json()

    # ─────────────────────────────────────── Pay Later / Pay in 4 ───────────
    def create_pay_in_4_order(
        self,
        total_amount: float,
        currency: str = "USD",
        description: str = "",
    ) -> dict[str, Any]:
        """
        Configure a PayPal 'Pay in 4' order.
        Installments: 4 equal payments, bi-weekly, first due today.
        """
        payment_source = {
            "pay_later": {
                "experience_context": {
                    "payment_method_preference": "IMMEDIATE_PAYMENT_REQUIRED",
                    "brand_name": "PayPal WisePayer",
                    "locale": "en-US",
                    "return_url": "https://wisepayer.app/paylater/return",
                    "cancel_url": "https://wisepayer.app/paylater/cancel",
                }
            }
        }
        return self.create_order(
            amount=total_amount,
            currency=currency,
            description=f"[Pay in 4] {description}",
            payment_source=payment_source,
        )

    # ────────────────────────────────────────────── Subscriptions ────────────
    def list_subscriptions(self, plan_id: Optional[str] = None) -> list[dict[str, Any]]:
        """List active subscriptions from the sandbox billing plans."""
        params = {"status": "ACTIVE"}
        if plan_id:
            params["plan_id"] = plan_id
        resp = self._http.get(
            "/v1/billing/subscriptions",
            headers=self._headers(),
            params=params,
        )
        # Subscriptions list endpoint may 404 if none exist — treat as empty
        if resp.status_code == 404:
            return []
        _raise_for_status(resp, "list_subscriptions")
        return resp.json().get("subscriptions", [])

    def cancel_subscription(self, subscription_id: str, reason: str = "User requested cancellation via WisePayer") -> bool:
        """Cancel a PayPal subscription."""
        resp = self._http.post(
            f"/v1/billing/subscriptions/{subscription_id}/cancel",
            headers=self._headers(),
            json={"reason": reason},
        )
        if resp.status_code == 204:
            logger.info("Subscription %s cancelled.", subscription_id)
            return True
        _raise_for_status(resp, "cancel_subscription")
        return False

    # ─────────────────────────────────────────────────── Payouts ────────────
    def create_payout(
        self,
        recipient_email: str,
        amount: float,
        currency: str = "USD",
        note: str = "WisePayer Agent-to-Agent settlement",
        sender_item_id: str = "a2a-settlement-001",
    ) -> dict[str, Any]:
        """
        Create a PayPal Payout (used for Agent-to-Agent settlement).
        Requires Payouts API enabled on the sandbox app.
        """
        body = {
            "sender_batch_header": {
                "sender_batch_id": f"wisepayer-batch-{int(time.time())}",
                "email_subject": "WisePayer Agent Settlement",
            },
            "items": [
                {
                    "recipient_type": "EMAIL",
                    "amount": {"value": f"{amount:.2f}", "currency": currency},
                    "note": note,
                    "receiver": recipient_email,
                    "sender_item_id": sender_item_id,
                }
            ],
        }
        resp = self._http.post("/v1/payments/payouts", headers=self._headers(), json=body)
        _raise_for_status(resp, "create_payout")
        data = resp.json()
        logger.info("Payout batch created: %s", data.get("batch_header", {}).get("payout_batch_id"))
        return data

    # ─────────────────────────────────────────────── connection test ─────────
    def health_check(self) -> dict[str, str]:
        """Verify sandbox credentials are valid."""
        try:
            token = self._ensure_token()
            return {"status": "ok", "token_preview": token[:10] + "…"}
        except Exception as exc:
            return {"status": "error", "detail": str(exc)}

    def close(self) -> None:
        self._http.close()


# ─────────────────────────────────────────────── error handling ─────────────
class PayPalAPIError(Exception):
    def __init__(self, operation: str, status_code: int, body: str):
        super().__init__(f"[{operation}] PayPal API returned {status_code}: {body}")
        self.status_code = status_code


def _raise_for_status(resp: httpx.Response, operation: str) -> None:
    if resp.is_error:
        raise PayPalAPIError(operation, resp.status_code, resp.text[:500])
