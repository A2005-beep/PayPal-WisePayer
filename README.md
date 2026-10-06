# 🛡️ PayPal WisePayer

**Autonomous Cashflow Guardian & Agentic Commerce Engine**

> Built for the [PayPal AI Hackathon](https://paypalaihackathon.devpost.com/) — uses **PayPal Developer Platform** + **AI** to prevent overdrafts, negotiate purchases, and autonomously execute safe transactions.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11+-green.svg)](backend/requirements.txt)
[![React](https://img.shields.io/badge/React-18-blue.svg)](frontend/package.json)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111-teal.svg)](backend/requirements.txt)
[![PayPal Sandbox](https://img.shields.io/badge/PayPal-Sandbox-blue.svg)](https://developer.paypal.com)

---

## 🎯 What It Does

WisePayer is an AI copilot that lives in the checkout flow. Before any purchase is made, it:

1. **Forecasts 30-day cashflow** with confidence bands — accounts for upcoming bills, salary, and recurring subscriptions
2. **Selects the optimal payment strategy**: full payment, Pay in 4, Smart Wait Hold, or decline
3. **Negotiates with a Merchant Agent** (A2A commerce) to get a discount or custom installment plan
4. **Executes via PayPal Sandbox**: Orders v2, Pay Later, Subscriptions, Payouts
5. **Shows you exactly why** with the "Explain My No" reasoning card

### Key Features

| Feature | Description | Prize Target |
|---|---|---|
| 🤝 A2A Negotiation | Buyer Agent ↔ Merchant Agent negotiate price/terms | Best Use of Agentic Commerce |
| 📊 AG Grid Cashflow | 30-day ledger with confidence bands, event tags | Best Use of AG Grid |
| 📅 Smart Wait Hold | Auto-executes when salary arrives via PayPal Webhook | Best Use of Agentic Commerce |
| 💸 Subscription Leaks | Detects forgotten subscriptions, 1-tap PayPal cancel | Most Impactful |
| 🛡️ WiseScore | 0–100 financial health gamification | Most Impactful |
| 🏗️ Autonomy Ladder | Advise / Bounded / Full Guardian modes | Technological Implementation |

---

## 🚀 Quick Start

### Prerequisites
- Python 3.11+
- Node.js 18+
- PayPal Sandbox credentials ([get them here](https://developer.paypal.com/dashboard/applications/sandbox))
- Gemini API Key ([get it here](https://aistudio.google.com/app/apikey))

### 1. Clone & Configure

```bash
git clone https://github.com/YOUR_USERNAME/paypal-wisepayer.git
cd paypal-wisepayer

# Set up environment variables
cp .env.example .env
# Edit .env and add your PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET, GEMINI_API_KEY
```

### 2. Start the Backend (FastAPI)

```bash
cd backend
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # Mac/Linux
pip install -r requirements.txt
uvicorn api.main:app --reload --port 8000
```

Backend runs at: **http://localhost:8000**  
API docs at: **http://localhost:8000/docs**

### 3. Start the Frontend (React)

```bash
cd frontend
npm install
npm run dev
```

Frontend runs at: **http://localhost:3000**

### 4. Run Tests

```bash
# From project root, with backend venv activated
pytest tests/ -v
```

---

## 🔑 Test Credentials (Sandbox)

Add these to your `.env` file. The sandbox environment uses PayPal's test accounts — no real money moves.

```
PAYPAL_CLIENT_ID=<your-sandbox-client-id>
PAYPAL_CLIENT_SECRET=<your-sandbox-client-secret>
```

To get sandbox buyer/seller accounts: [PayPal Sandbox Accounts](https://developer.paypal.com/dashboard/accounts)

---

## 🏗️ Architecture

```
paypal-wisepayer/
├── backend/
│   ├── engine/
│   │   ├── cashflow_model.py      # 30-day rolling forecast engine
│   │   └── wise_score.py          # WiseScore 0–100 computation
│   ├── agent/
│   │   ├── buyer_agent.py         # AI Buyer Agent (Gemini + tools)
│   │   └── merchant_agent.py      # A2A Merchant Agent (negotiation)
│   ├── paypal/
│   │   └── sandbox_client.py      # PayPal REST API v2 client
│   ├── api/
│   │   └── main.py                # FastAPI (12 endpoints)
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── api/
│       │   └── wisepayerApi.ts    # Typed API client
│       ├── components/
│       │   ├── GuardianCard.tsx   # Main checkout decision card
│       │   ├── CashflowGrid.tsx   # AG Grid 30-day ledger
│       │   ├── WiseScoreCard.tsx  # Circular score + insights
│       │   └── SubscriptionLeakDetector.tsx
│       └── pages/
│           └── Dashboard.tsx      # 4-tab main app
├── tests/
│   └── test_engine.py             # 14 pytest tests
├── render.yaml                    # Render deployment blueprint
├── .env.example
└── LICENSE (MIT)
```

---

## 🔌 PayPal APIs Used

| API | Endpoint | Usage |
|---|---|---|
| OAuth 2.0 | `/v1/oauth2/token` | Auto-refreshing access token |
| Orders v2 | `/v2/checkout/orders` | Create, capture, void checkout sessions |
| Pay Later | Orders + `payment_source.pay_later` | Pay in 4 installment configuration |
| Subscriptions | `/v1/billing/subscriptions` | Detect & 1-tap cancel leaks |
| Payouts | `/v1/payments/payouts` | Agent-to-Agent settlement |
| Webhooks | `PAYMENT.SALE.COMPLETED` | Smart Wait Hold auto-release trigger |

---

## 🤝 A2A Agent Negotiation Protocol

```
POST /a2a/merchant/negotiate
{
  "buyer_agent_id": "wisepayer-buyer-001",
  "product_name": "Sony Headphones",
  "list_price": 350.00,
  "buyer_budget": 310.00,
  "proposed_discount_pct": 11.4,
  "allow_installments": true
}

Response:
{
  "accepted": false,
  "counter_type": "counter_installment",
  "final_price": 350.00,
  "installment_plan": [
    {"due_date": "today", "amount": 175.00},
    {"due_date": "+30 days", "amount": 175.00}
  ],
  "merchant_message": "⚡ Demo Merchant offers 2-part payment: $175 today + $175 in 30 days."
}
```

---

## 📅 Hackathon Updates Made During Submission Period

This project was created from scratch after **October 1, 2026** (hackathon start):

- ✅ Complete FastAPI backend with PayPal Sandbox integration
- ✅ React + AG Grid + Bryntum + Framer Motion frontend
- ✅ 3-tier Autonomy Ladder (Advise / Bounded / Full Guardian)
- ✅ A2A Buyer-Merchant negotiation protocol
- ✅ "Explain My No" LLM-generated reasoning card (Gemini)
- ✅ Smart Wait Hold with PayPal Webhook trigger
- ✅ Subscription Leak Detector with 1-tap PayPal cancel
- ✅ WiseScore 0–100 gamified financial health score
- ✅ Render deployment blueprint (`render.yaml`)

---

## 📹 Demo Video

[▶ Watch the 3-minute demo on YouTube](#) ← *Link added before submission deadline*

---

## 🏆 Prize Categories Targeted

- Best Use of Agentic Commerce (\$5,000)
- Grand Prize (\$12,000)
- Best Use of AG Grid (\$5,000)
- Best Use of Channel3 (\$1,500)
- Best Use of Bryntum (\$1,000)
- Best Use of Render (credits)

---

## 📄 License

MIT — see [LICENSE](LICENSE)
