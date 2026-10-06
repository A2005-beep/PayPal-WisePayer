import axios from 'axios'

const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

const api = axios.create({
  baseURL: BASE_URL,
  headers: { 'Content-Type': 'application/json' },
})

export interface EvaluatePayload {
  user_id: string
  product_name: string
  amount: number
  currency?: string
  product_url?: string
  merchant_agent_url?: string
  desired_date?: string
  autonomy_level?: 0 | 1 | 2
  bounded_limit?: number
  current_balance: number
  minimum_balance?: number
  events?: object[]
}

export interface AgentDecisionResponse {
  affordability_status: 'affordable_now' | 'affordable_with_plan' | 'affordable_later' | 'not_affordable'
  recommended_action: 'full_payment' | 'pay_in_4' | 'smart_wait' | 'not_recommended'
  safe_to_pay_today: number
  earliest_safe_date: string | null
  negotiated_amount: number | null
  payment_plan: Array<{ date: string; amount: number }>
  explain_my_no: string
  wise_score: number
  autonomy_level: 'ADVISE' | 'BOUNDED' | 'GUARDIAN'
  paypal_order_id: string | null
  rollback_deadline: string | null
}

export interface CashflowRow {
  date: string
  projected_balance: number
  reserved_essential: number
  available_discretionary: number
  confidence_low: number
  confidence_high: number
  events: Array<{
    event_id: string
    description: string
    amount: number
    direction: 'inflow' | 'outflow'
    is_essential: boolean
    is_subscription: boolean
  }>
}

export interface WiseScoreResponse {
  user_id: string
  score: number
  grade: string
  liquidity_ratio: number
  overdraft_risk_days: number
  subscription_waste_annual: number
  insights: string[]
}

export interface SubscriptionLeak {
  event_id: string
  description: string
  amount_per_cycle: number
  recurrence_days: number
  annual_cost: number
  category: string
  last_seen: string
}

export interface SmartWaitHold {
  id: string
  user_id: string
  product_name: string
  amount: number
  execute_date: string
  created_at: string
  status: string
}

export const wisepayerApi = {
  health: () => api.get('/health'),

  evaluate: (payload: EvaluatePayload) =>
    api.post<AgentDecisionResponse>('/evaluate', payload),

  merchantNegotiate: (payload: object) =>
    api.post('/a2a/merchant/negotiate', payload),

  getCashflow: (userId: string, balance: number, minBalance = 200) =>
    api.get<{ cashflow_rows: CashflowRow[]; summary: object }>(
      `/cashflow/${userId}`,
      { params: { balance, min_balance: minBalance } }
    ),

  getWiseScore: (userId: string, balance: number, minBalance = 200) =>
    api.get<WiseScoreResponse>(`/wise-score/${userId}`, {
      params: { balance, min_balance: minBalance },
    }),

  getSubscriptionLeaks: (userId: string, balance: number, minBalance = 200) =>
    api.get<{ leaks: SubscriptionLeak[]; total_annual_waste: number }>(
      `/subscription-leaks/${userId}`,
      { params: { balance, min_balance: minBalance } }
    ),

  cancelSubscription: (subscriptionId: string) =>
    api.post(`/subscription/${subscriptionId}/cancel`),

  getSmartWaitHolds: () => api.get<{ holds: SmartWaitHold[] }>('/smart-wait-holds'),

  cancelSmartWaitHold: (holdId: string) =>
    api.delete(`/smart-wait-holds/${holdId}/cancel`),
}
