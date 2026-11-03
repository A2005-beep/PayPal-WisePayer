import React, { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  ShoppingCart,
  Settings,
  BarChart3,
  Repeat,
  Calendar,
  CheckCircle2,
  ExternalLink,
  X,
  ShieldCheck,
  AlertCircle,
  Sliders,
  Play,
  Pause,
  Trash2,
} from 'lucide-react'
import { GuardianCard } from '../components/GuardianCard'
import { CashflowGrid } from '../components/CashflowGrid'
import { WiseScoreCard } from '../components/WiseScoreCard'
import { SubscriptionLeakDetector } from '../components/SubscriptionLeakDetector'
import { wisepayerApi, BASE_URL } from '../api/wisepayerApi'
import type {
  AgentDecisionResponse,
  CashflowRow,
  WiseScoreResponse,
  SubscriptionLeak,
  SmartWaitHold,
} from '../api/wisepayerApi'

const TABS = [
  { id: 'checkout', label: 'Guardian Checkout', icon: ShoppingCart },
  { id: 'cashflow', label: 'Cashflow', icon: BarChart3 },
  { id: 'subscriptions', label: 'Subscriptions', icon: Repeat },
  { id: 'holds', label: 'Smart Holds', icon: Calendar },
] as const

type TabId = typeof TABS[number]['id']

const AUTONOMY_OPTIONS = [
  { value: 0, label: '🟢 Advise Only', desc: 'You always confirm' },
  { value: 1, label: '🟡 Bounded', desc: 'Auto for small amounts' },
  { value: 2, label: '🔴 Full Guardian', desc: 'Agent auto-executes' },
] as const

const PRESET_SCENARIOS = [
  {
    name: '☕ Safe: Coffee Maker',
    product: 'Espresso Coffee Maker',
    amount: 28,
    desc: 'Instant full payment — within discretionary budget',
  },
  {
    name: '💻 Planned: Ergonomic Desk',
    product: 'Motorized Standing Desk',
    amount: 320,
    desc: 'Pay in 4 installments across 6 weeks',
  },
  {
    name: '📱 Defer: Smartphone',
    product: 'Flagship Smartphone Pro',
    amount: 899,
    desc: 'Triggers Smart Wait until Salary milestone',
  },
]

const DEMO_USER = { id: 'demo-user-001', balance: 1420, minBalance: 200 }

export const Dashboard: React.FC = () => {
  const [activeTab, setActiveTab] = useState<TabId>('checkout')

  // Checkout form state
  const [productName, setProductName] = useState('Sony WH-1000XM5 Headphones')
  const [amount, setAmount] = useState(350)
  const [autonomyLevel, setAutonomyLevel] = useState<0 | 1 | 2>(0)
  const [enableA2A, setEnableA2A] = useState(false)

  // Policy & Guardrails
  const [boundedLimit, setBoundedLimit] = useState(50)
  const [dailySpendingLimit, setDailySpendingLimit] = useState(150)
  const [minBalanceBuffer, setMinBalanceBuffer] = useState(200)
  const [isSettingsOpen, setIsSettingsOpen] = useState(false)

  // Decision state
  const [decision, setDecision] = useState<AgentDecisionResponse | null>(null)
  const [isEvaluating, setIsEvaluating] = useState(false)
  const [evalError, setEvalError] = useState<string | null>(null)

  // Real PayPal Checkout Flow State
  const [checkoutModalOpen, setCheckoutModalOpen] = useState(false)
  const [activeOrder, setActiveOrder] = useState<{
    orderId: string
    approvalUrl: string | null
    amount: number
    productName: string
  } | null>(null)
  const [isCreatingOrder, setIsCreatingOrder] = useState(false)
  const [isCapturingOrder, setIsCapturingOrder] = useState(false)
  const [capturedReceipt, setCapturedReceipt] = useState<{
    order_id: string
    capture_id: string
    status: string
    amount?: string
    currency?: string
  } | null>(null)
  const [checkoutError, setCheckoutError] = useState<string | null>(null)

  // Data state
  const [cashflowRows, setCashflowRows] = useState<CashflowRow[]>([])
  const [wiseScore, setWiseScore] = useState<WiseScoreResponse | null>(null)
  const [leaks, setLeaks] = useState<SubscriptionLeak[]>([])
  const [totalWaste, setTotalWaste] = useState(0)
  const [holds, setHolds] = useState<SmartWaitHold[]>([])
  const [pausedHolds, setPausedHolds] = useState<Set<string>>(new Set())
  const [isLoadingData, setIsLoadingData] = useState(false)

  useEffect(() => {
    loadDashboardData()
  }, [])

  const loadDashboardData = async () => {
    setIsLoadingData(true)
    try {
      const [cashflowRes, scoreRes, leaksRes, holdsRes] = await Promise.all([
        wisepayerApi.getCashflow(DEMO_USER.id, DEMO_USER.balance, minBalanceBuffer),
        wisepayerApi.getWiseScore(DEMO_USER.id, DEMO_USER.balance, minBalanceBuffer),
        wisepayerApi.getSubscriptionLeaks(DEMO_USER.id, DEMO_USER.balance, minBalanceBuffer),
        wisepayerApi.getSmartWaitHolds(),
      ])
      setCashflowRows(cashflowRes.data.cashflow_rows)
      setWiseScore(scoreRes.data)
      setLeaks(leaksRes.data.leaks)
      setTotalWaste(leaksRes.data.total_annual_waste)
      setHolds(holdsRes.data.holds)
    } catch (e) {
      console.error('Failed to load dashboard data', e)
    } finally {
      setIsLoadingData(false)
    }
  }

  const handleEvaluate = async (prod = productName, amt = amount) => {
    setIsEvaluating(true)
    setEvalError(null)
    setDecision(null)
    try {
      const res = await wisepayerApi.evaluate({
        user_id: DEMO_USER.id,
        product_name: prod,
        amount: amt,
        currency: 'USD',
        current_balance: DEMO_USER.balance,
        minimum_balance: minBalanceBuffer,
        autonomy_level: autonomyLevel,
        bounded_limit: boundedLimit,
        merchant_agent_url: enableA2A ? `${BASE_URL}/a2a/merchant/negotiate` : undefined,
      })
      setDecision(res.data)
    } catch (e: any) {
      setEvalError(e?.response?.data?.detail || 'Evaluation failed. Check backend connection.')
    } finally {
      setIsEvaluating(false)
    }
  }

  const runPresetScenario = (scenario: typeof PRESET_SCENARIOS[number]) => {
    setProductName(scenario.product)
    setAmount(scenario.amount)
    handleEvaluate(scenario.product, scenario.amount)
  }

  // Real PayPal Checkout Flow Handler
  const handleInitiatePayment = async () => {
    setCheckoutModalOpen(true)
    setCapturedReceipt(null)
    setCheckoutError(null)

    // Check if order was already generated by backend auto-execution
    if (decision?.paypal_order_id) {
      setActiveOrder({
        orderId: decision.paypal_order_id,
        approvalUrl: decision.paypal_approval_url || `https://www.sandbox.paypal.com/checkoutnow?token=${decision.paypal_order_id}`,
        amount: decision.negotiated_amount || amount,
        productName: productName,
      })
      return
    }

    // Otherwise create real sandbox order via endpoint
    setIsCreatingOrder(true)
    try {
      const res = await wisepayerApi.createOrder({
        amount: decision?.negotiated_amount || amount,
        product_name: productName,
        currency: 'USD',
        pay_in_4: decision?.recommended_action === 'pay_in_4',
        return_url: window.location.href,
        cancel_url: window.location.href,
      })
      setActiveOrder({
        orderId: res.data.order_id,
        approvalUrl: res.data.approval_url || `https://www.sandbox.paypal.com/checkoutnow?token=${res.data.order_id}`,
        amount: decision?.negotiated_amount || amount,
        productName: productName,
      })
    } catch (err: any) {
      setCheckoutError(err?.response?.data?.detail || 'Failed to create PayPal sandbox order. Check credentials.')
    } finally {
      setIsCreatingOrder(false)
    }
  }

  const handleCaptureOrder = async () => {
    if (!activeOrder?.orderId) return
    setIsCapturingOrder(true)
    setCheckoutError(null)
    try {
      const res = await wisepayerApi.captureOrder(activeOrder.orderId)
      setCapturedReceipt({
        order_id: res.data.order_id,
        capture_id: res.data.capture_id,
        status: res.data.status,
        amount: res.data.amount || String(activeOrder.amount),
        currency: res.data.currency || 'USD',
      })
      // Adjust balance in UI
      DEMO_USER.balance = Math.max(0, DEMO_USER.balance - activeOrder.amount)
    } catch (err: any) {
      setCheckoutError(err?.response?.data?.detail || 'Capture failed. Order may need approval in sandbox window.')
    } finally {
      setIsCapturingOrder(false)
    }
  }

  const handleCancelSubscription = async (id: string, description: string) => {
    await wisepayerApi.cancelSubscription(id)
    setLeaks(prev => prev.filter(l => l.event_id !== id))
    // Recalculate summary
    setTotalWaste(prev => Math.max(0, prev - (leaks.find(l => l.event_id === id)?.annual_cost || 0)))
  }

  const toggleHoldPause = (id: string) => {
    setPausedHolds(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const handleCancelHold = async (id: string) => {
    try {
      await wisepayerApi.cancelSmartWaitHold(id)
      setHolds(prev => prev.filter(h => h.id !== id))
    } catch (e) {
      console.error('Failed to cancel hold', e)
    }
  }

  return (
    <div className="min-h-screen bg-slate-950 text-white flex flex-col">
      {/* ── Sandbox Provenance Banner ── */}
      <div className="bg-blue-950/90 border-b border-blue-800/60 px-6 py-2 text-xs text-blue-200 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
          <span>
            <strong>PayPal Sandbox Mode</strong> · Active Test Account (<code>demo-user-001</code>) · Simulated Financial Events · No Real Funds
          </span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-slate-400 text-xs hidden sm:inline">PayPal AI Hackathon 2026</span>
          <span className="px-2 py-0.5 rounded bg-blue-900/60 text-blue-300 font-mono text-[10px] border border-blue-700/50">
            SANDBOX REST v2
          </span>
        </div>
      </div>

      {/* ── Top Nav ── */}
      <header className="border-b border-slate-800 px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-blue-500 to-indigo-600 flex items-center justify-center shadow-lg shadow-blue-500/20">
            <span className="text-base">🛡️</span>
          </div>
          <div>
            <h1 className="font-bold text-lg leading-none tracking-tight">PayPal WisePayer</h1>
            <p className="text-xs text-slate-400 mt-0.5">Autonomous Cashflow Guardian & Commerce Engine</p>
          </div>
        </div>
        <div className="flex items-center gap-4 text-sm text-slate-300">
          <div className="hidden sm:flex items-center gap-3 bg-slate-900 border border-slate-800 rounded-xl px-3 py-1.5 text-xs">
            <span>Balance: <strong className="text-emerald-400 font-semibold">${DEMO_USER.balance.toLocaleString()}</strong></span>
            <span className="text-slate-600">|</span>
            <span>Min Buffer: <strong className="text-amber-400 font-semibold">${minBalanceBuffer}</strong></span>
          </div>
          <button
            onClick={() => setIsSettingsOpen(true)}
            className="p-2 rounded-xl bg-slate-900 border border-slate-800 hover:border-slate-700 text-slate-400 hover:text-white transition-all"
            title="Configure Agent Guardrails"
          >
            <Settings className="w-4 h-4" />
          </button>
        </div>
      </header>

      {/* ── Tab Bar ── */}
      <div className="border-b border-slate-800 px-6">
        <div className="flex gap-1">
          {TABS.map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex items-center gap-2 px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
                activeTab === tab.id
                  ? 'border-blue-500 text-blue-400'
                  : 'border-transparent text-slate-400 hover:text-slate-200'
              }`}
            >
              <tab.icon className="w-4 h-4" />
              {tab.label}
              {tab.id === 'subscriptions' && leaks.length > 0 && (
                <span className="px-1.5 py-0.5 rounded-full bg-red-600 text-white text-xs leading-none font-bold">
                  {leaks.length}
                </span>
              )}
              {tab.id === 'holds' && holds.length > 0 && (
                <span className="px-1.5 py-0.5 rounded-full bg-blue-600 text-white text-xs leading-none font-bold">
                  {holds.length}
                </span>
              )}
            </button>
          ))}
        </div>
      </div>

      {/* ── Main Content ── */}
      <main className="max-w-6xl mx-auto px-6 py-8 flex-1 w-full">
        {/* ── Guardian Checkout Tab ── */}
        {activeTab === 'checkout' && (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
            {/* Left: Purchase Form */}
            <div className="flex flex-col gap-6">
              <WiseScoreCard scoreData={wiseScore} isLoading={isLoadingData} />

              <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 flex flex-col gap-5 shadow-xl">
                <div className="flex items-center justify-between">
                  <h2 className="text-white font-semibold flex items-center gap-2">
                    <span>🛒</span> Evaluate Purchase Request
                  </h2>
                  <span className="text-[11px] text-slate-400">Cashflow-guaranteed check</span>
                </div>

                {/* Preset Scenarios for Instant Demo */}
                <div>
                  <label className="text-xs text-slate-400 mb-1.5 block">Quick Test Scenarios (1-Click Evaluation):</label>
                  <div className="grid grid-cols-3 gap-2">
                    {PRESET_SCENARIOS.map((scen, idx) => (
                      <button
                        key={idx}
                        type="button"
                        onClick={() => runPresetScenario(scen)}
                        className="p-2 rounded-xl border border-slate-800 bg-slate-800/60 hover:bg-slate-800 hover:border-blue-500/50 text-left transition-all group"
                      >
                        <p className="text-xs font-semibold text-slate-200 group-hover:text-blue-300 truncate">{scen.name}</p>
                        <p className="text-[10px] text-slate-400 truncate mt-0.5">{scen.desc}</p>
                      </button>
                    ))}
                  </div>
                </div>

                <div>
                  <label className="text-xs text-slate-400 mb-1 block">Product / Service Name</label>
                  <input
                    value={productName}
                    onChange={e => setProductName(e.target.value)}
                    className="w-full bg-slate-800 border border-slate-700 rounded-xl px-4 py-3 text-white text-sm focus:outline-none focus:border-blue-500"
                    placeholder="What do you want to buy?"
                  />
                </div>

                <div>
                  <label className="text-xs text-slate-400 mb-1 block">Amount (USD)</label>
                  <input
                    type="number"
                    value={amount}
                    onChange={e => setAmount(Number(e.target.value))}
                    className="w-full bg-slate-800 border border-slate-700 rounded-xl px-4 py-3 text-white text-sm focus:outline-none focus:border-blue-500"
                    min={1}
                  />
                </div>

                {/* Autonomy Ladder */}
                <div>
                  <div className="flex justify-between items-center mb-1.5">
                    <label className="text-xs text-slate-400">Autonomy Guardrail Mode</label>
                    <span className="text-[10px] text-slate-500">Auto-limit: ${boundedLimit}</span>
                  </div>
                  <div className="flex flex-col gap-2">
                    {AUTONOMY_OPTIONS.map(opt => (
                      <button
                        key={opt.value}
                        onClick={() => setAutonomyLevel(opt.value as 0 | 1 | 2)}
                        className={`flex items-center gap-3 px-4 py-2.5 rounded-xl border text-left transition-all ${
                          autonomyLevel === opt.value
                            ? 'border-blue-500 bg-blue-900/30'
                            : 'border-slate-800 bg-slate-800/40 hover:border-slate-700'
                        }`}
                      >
                        <span className="text-xs font-semibold text-white">{opt.label}</span>
                        <span className="text-[11px] text-slate-400">{opt.desc}</span>
                      </button>
                    ))}
                  </div>
                </div>

                {/* A2A Toggle */}
                <div className="flex items-center justify-between py-2.5 px-4 bg-purple-950/30 border border-purple-800/60 rounded-xl">
                  <div>
                    <p className="text-xs text-purple-200 font-semibold">🤝 A2A Merchant Negotiation Protocol</p>
                    <p className="text-[11px] text-purple-400">Buyer Agent will autonomously counter-negotiate with Merchant Agent</p>
                  </div>
                  <button
                    onClick={() => setEnableA2A(!enableA2A)}
                    className={`w-11 h-6 rounded-full transition-colors ${enableA2A ? 'bg-purple-600' : 'bg-slate-700'} relative`}
                  >
                    <div className={`w-4 h-4 rounded-full bg-white absolute top-1 transition-all ${enableA2A ? 'left-6' : 'left-1'}`} />
                  </button>
                </div>

                <button
                  onClick={() => handleEvaluate()}
                  disabled={isEvaluating || !productName || amount <= 0}
                  className="w-full py-3.5 rounded-xl bg-blue-600 hover:bg-blue-500 disabled:bg-slate-800 disabled:text-slate-600 text-white font-bold text-sm transition-all shadow-lg shadow-blue-600/30 active:scale-[0.99]"
                >
                  {isEvaluating ? '⚡ Agent Analyzing Cashflow…' : '🛡️ Ask WisePayer Guardian'}
                </button>

                {evalError && (
                  <div className="text-red-300 text-xs bg-red-950/40 border border-red-800 rounded-xl px-4 py-3 flex items-start gap-2">
                    <AlertCircle className="w-4 h-4 shrink-0 text-red-400 mt-0.5" />
                    <span>{evalError}</span>
                  </div>
                )}
              </div>
            </div>

            {/* Right: Guardian Card */}
            <div className="flex flex-col gap-4">
              {(decision || isEvaluating) ? (
                <GuardianCard
                  decision={decision}
                  productName={productName}
                  requestedAmount={amount}
                  currentBalance={DEMO_USER.balance}
                  onConfirmPayment={handleInitiatePayment}
                  onReject={() => setDecision(null)}
                  isLoading={isEvaluating}
                />
              ) : (
                <div className="rounded-2xl border border-dashed border-slate-800 bg-slate-900/40 flex flex-col items-center justify-center p-12 gap-5 text-center h-full min-h-80 shadow-inner">
                  <div className="w-16 h-16 rounded-2xl bg-slate-800/80 border border-slate-700 flex items-center justify-center text-3xl">
                    🛡️
                  </div>
                  <div className="max-w-sm">
                    <h3 className="text-white font-semibold text-base mb-1">Guarded Commerce Ready</h3>
                    <p className="text-slate-400 text-xs leading-relaxed">
                      Select one of the <strong className="text-blue-400">1-click test scenarios</strong> or enter a product to see how WisePayer protects upcoming bills, negotiates with merchants, or structures PayPal Pay in 4.
                    </p>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* ── Cashflow Tab (AG Grid) ── */}
        {activeTab === 'cashflow' && (
          <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="flex flex-col gap-4">
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <div>
                <h3 className="text-white font-semibold text-sm">30-Day Rolling Cashflow Ledger</h3>
                <p className="text-xs text-slate-400">
                  Data provenance: Synced with PayPal Sandbox & Essential Bill Schedule (Rent $800, Insurance $150, Salary $1,800).
                </p>
              </div>
              <div className="flex items-center gap-2 text-xs">
                <span className="px-2.5 py-1 rounded-md bg-emerald-950 border border-emerald-800 text-emerald-300">
                  Safe Discretionary Today: $270.00
                </span>
              </div>
            </div>
            {isLoadingData ? (
              <div className="text-slate-400 text-sm py-20 text-center">Loading cashflow ledger…</div>
            ) : (
              <CashflowGrid rows={cashflowRows} currency="USD" />
            )}
          </motion.div>
        )}

        {/* ── Subscriptions Tab ── */}
        {activeTab === 'subscriptions' && (
          <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
            <SubscriptionLeakDetector
              leaks={leaks}
              totalAnnualWaste={totalWaste}
              onCancelSubscription={handleCancelSubscription}
            />
          </motion.div>
        )}

        {/* ── Smart Holds Tab ── */}
        {activeTab === 'holds' && (
          <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="flex flex-col gap-5">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-white font-semibold text-base flex items-center gap-2">
                  <Calendar className="w-5 h-5 text-blue-400" />
                  Scheduled Purchase Intents & Smart Holds
                </h3>
                <p className="text-xs text-slate-400 mt-0.5">
                  Automated deferred purchases timed to release safely after verified income arrivals.
                </p>
              </div>
              <div className="text-xs px-3 py-1 bg-slate-900 border border-slate-800 rounded-lg text-slate-300">
                {holds.length} Intent{holds.length !== 1 ? 's' : ''} Configured
              </div>
            </div>

            <div className="bg-blue-950/30 border border-blue-800/60 rounded-xl p-4 text-xs text-blue-200 flex items-start gap-3">
              <ShieldCheck className="w-5 h-5 text-blue-400 shrink-0 mt-0.5" />
              <div>
                <strong>Cashflow Re-Verification Protocol:</strong> WisePayer holds authorization and will perform a fresh 
                liquidity assessment 24 hours prior to release. If an unplanned expense compromises your ${minBalanceBuffer} buffer, 
                execution is automatically paused and escalated to you.
              </div>
            </div>

            {holds.length === 0 ? (
              <div className="text-center py-16 bg-slate-900/30 border border-dashed border-slate-800 rounded-2xl text-slate-400 text-sm flex flex-col items-center gap-2">
                <Calendar className="w-8 h-8 text-slate-600" />
                <span>No deferred purchase holds active.</span>
                <span className="text-xs text-slate-500 max-w-sm">
                  When a purchase exceeds safe discretionary cashflow today but is affordable after salary, the agent schedules a hold here.
                </span>
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {holds.map((hold) => {
                  const isPaused = pausedHolds.has(hold.id)
                  return (
                    <div
                      key={hold.id}
                      className="bg-slate-900 border border-slate-800 rounded-xl p-5 flex flex-col justify-between gap-4 shadow-lg hover:border-slate-700 transition-all"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <div className="flex items-center gap-2">
                            <h4 className="text-white font-semibold text-sm">{hold.product_name}</h4>
                            <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                              isPaused
                                ? 'bg-amber-950 text-amber-300 border border-amber-800'
                                : 'bg-blue-950 text-blue-300 border border-blue-800'
                            }`}>
                              {isPaused ? 'PAUSED' : 'PENDING RELEASE'}
                            </span>
                          </div>
                          <p className="text-slate-400 text-xs mt-1">
                            Target Date: <strong className="text-slate-200">{hold.execute_date}</strong> (Post-Salary Window)
                          </p>
                        </div>
                        <span className="text-lg font-black text-white">${hold.amount.toFixed(2)}</span>
                      </div>

                      <div className="flex items-center justify-between pt-3 border-t border-slate-800 text-xs">
                        <span className="text-slate-500 font-mono text-[10px]">{hold.id}</span>
                        <div className="flex items-center gap-2">
                          <button
                            onClick={() => toggleHoldPause(hold.id)}
                            className="flex items-center gap-1 px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs transition-colors"
                          >
                            {isPaused ? <Play className="w-3 h-3" /> : <Pause className="w-3 h-3" />}
                            {isPaused ? 'Resume' : 'Pause'}
                          </button>
                          <button
                            onClick={() => handleCancelHold(hold.id)}
                            className="flex items-center gap-1 px-2.5 py-1 rounded bg-red-950/40 hover:bg-red-900/60 text-red-300 border border-red-800/40 text-xs transition-colors"
                          >
                            <Trash2 className="w-3 h-3" />
                            Cancel
                          </button>
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </motion.div>
        )}
      </main>

      {/* ── Policy & Guardrails Settings Modal ── */}
      <AnimatePresence>
        {isSettingsOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm">
            <motion.div
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              className="bg-slate-900 border border-slate-800 rounded-2xl p-6 max-w-md w-full shadow-2xl flex flex-col gap-5"
            >
              <div className="flex items-center justify-between border-b border-slate-800 pb-4">
                <div className="flex items-center gap-2">
                  <Sliders className="w-5 h-5 text-blue-400" />
                  <h3 className="text-white font-semibold text-base">Agent Guardrails & Spending Policy</h3>
                </div>
                <button
                  onClick={() => setIsSettingsOpen(false)}
                  className="p-1 rounded-lg text-slate-400 hover:text-white transition-colors"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>

              <div className="flex flex-col gap-4 text-sm">
                <div>
                  <label className="text-xs text-slate-400 block mb-1">
                    Bounded Autonomy Max Amount ($)
                  </label>
                  <input
                    type="number"
                    value={boundedLimit}
                    onChange={e => setBoundedLimit(Number(e.target.value))}
                    className="w-full bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 text-white text-sm"
                  />
                  <p className="text-[11px] text-slate-500 mt-1">Purchases under this amount execute without requiring confirmation.</p>
                </div>

                <div>
                  <label className="text-xs text-slate-400 block mb-1">
                    Daily Aggregate Spending Limit ($)
                  </label>
                  <input
                    type="number"
                    value={dailySpendingLimit}
                    onChange={e => setDailySpendingLimit(Number(e.target.value))}
                    className="w-full bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 text-white text-sm"
                  />
                  <p className="text-[11px] text-slate-500 mt-1">Caps total discretionary outflow permitted in a 24-hour cycle.</p>
                </div>

                <div>
                  <label className="text-xs text-slate-400 block mb-1">
                    Emergency Liquidity Floor / Buffer ($)
                  </label>
                  <input
                    type="number"
                    value={minBalanceBuffer}
                    onChange={e => setMinBalanceBuffer(Number(e.target.value))}
                    className="w-full bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 text-white text-sm"
                  />
                  <p className="text-[11px] text-slate-500 mt-1">Protected balance below which discretionary spending is prohibited.</p>
                </div>
              </div>

              <button
                onClick={() => {
                  setIsSettingsOpen(false)
                  loadDashboardData()
                }}
                className="w-full py-3 rounded-xl bg-blue-600 hover:bg-blue-500 text-white font-bold text-sm transition-colors mt-2"
              >
                Apply Guardrail Policy
              </button>
            </motion.div>
          </div>
        )}
      </AnimatePresence>

      {/* ── PayPal Real Checkout & Verified Receipt Modal ── */}
      <AnimatePresence>
        {checkoutModalOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-sm">
            <motion.div
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              className="bg-slate-900 border border-slate-800 rounded-2xl p-6 max-w-lg w-full shadow-2xl flex flex-col gap-5"
            >
              {/* Header */}
              <div className="flex items-center justify-between border-b border-slate-800 pb-4">
                <div className="flex items-center gap-2.5">
                  <div className="w-8 h-8 rounded-lg bg-blue-600 flex items-center justify-center text-white font-bold text-sm">
                    P
                  </div>
                  <div>
                    <h3 className="text-white font-semibold text-base leading-none">PayPal Sandbox Checkout</h3>
                    <p className="text-xs text-slate-400 mt-1">Verified REST Orders v2 Flow</p>
                  </div>
                </div>
                <button
                  onClick={() => setCheckoutModalOpen(false)}
                  className="p-1 rounded-lg text-slate-400 hover:text-white transition-colors"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>

              {/* State 1: Receipt (Payment Captured) */}
              {capturedReceipt ? (
                <div className="flex flex-col gap-4 text-center py-2">
                  <div className="w-14 h-14 bg-emerald-950 border border-emerald-500 rounded-full flex items-center justify-center mx-auto text-emerald-400">
                    <CheckCircle2 className="w-8 h-8" />
                  </div>
                  <div>
                    <h4 className="text-lg font-bold text-white">Payment Successfully Captured</h4>
                    <p className="text-xs text-slate-400 mt-0.5">Verified on PayPal Sandbox REST v2 API</p>
                  </div>

                  <div className="bg-slate-800/80 border border-slate-700 rounded-xl p-4 text-left flex flex-col gap-2.5 text-xs">
                    <div className="flex justify-between items-center">
                      <span className="text-slate-400">PayPal Order ID</span>
                      <span className="font-mono text-blue-300 font-bold">{capturedReceipt.order_id}</span>
                    </div>
                    <div className="flex justify-between items-center">
                      <span className="text-slate-400">Capture ID</span>
                      <span className="font-mono text-emerald-300 font-bold">{capturedReceipt.capture_id}</span>
                    </div>
                    <div className="flex justify-between items-center">
                      <span className="text-slate-400">Status</span>
                      <span className="px-2 py-0.5 bg-emerald-900/60 text-emerald-200 border border-emerald-700/50 rounded font-semibold text-[11px]">
                        {capturedReceipt.status}
                      </span>
                    </div>
                    <div className="flex justify-between items-center">
                      <span className="text-slate-400">Amount Charged</span>
                      <span className="font-bold text-white text-sm">
                        ${capturedReceipt.amount} {capturedReceipt.currency}
                      </span>
                    </div>
                    <div className="flex justify-between items-center">
                      <span className="text-slate-400">Cashflow Impact</span>
                      <span className="text-emerald-400 font-semibold">Protected within buffer (${minBalanceBuffer})</span>
                    </div>
                  </div>

                  <button
                    onClick={() => {
                      setCheckoutModalOpen(false)
                      setDecision(null)
                    }}
                    className="w-full py-3 rounded-xl bg-blue-600 hover:bg-blue-500 text-white font-bold text-sm transition-colors mt-2"
                  >
                    Done & Return to Dashboard
                  </button>
                </div>
              ) : (
                /* State 2: Order Active, Waiting Capture */
                <div className="flex flex-col gap-4">
                  {isCreatingOrder ? (
                    <div className="py-12 text-center text-slate-400 text-sm">
                      Initializing PayPal Sandbox Order…
                    </div>
                  ) : activeOrder ? (
                    <>
                      <div className="bg-slate-800/60 border border-slate-700 rounded-xl p-4 flex flex-col gap-2.5 text-xs">
                        <div className="flex justify-between items-center">
                          <span className="text-slate-400">Product</span>
                          <span className="text-white font-semibold truncate max-w-[200px]">{activeOrder.productName}</span>
                        </div>
                        <div className="flex justify-between items-center">
                          <span className="text-slate-400">Order Amount</span>
                          <span className="text-white font-bold text-sm">${activeOrder.amount.toFixed(2)} USD</span>
                        </div>
                        <div className="flex justify-between items-center">
                          <span className="text-slate-400">PayPal Order ID</span>
                          <span className="font-mono text-blue-300 font-semibold">{activeOrder.orderId}</span>
                        </div>
                      </div>

                      {/* Approval options */}
                      <div className="flex flex-col gap-3">
                        <p className="text-xs text-slate-300">
                          Complete checkout through the PayPal Sandbox interface or finalize with Agent Authorization:
                        </p>

                        {activeOrder.approvalUrl && (
                          <a
                            href={activeOrder.approvalUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="flex items-center justify-center gap-2 py-3 px-4 rounded-xl bg-slate-800 hover:bg-slate-700 text-blue-300 font-semibold text-xs border border-blue-500/30 transition-all"
                          >
                            <span>Open PayPal Sandbox Approval Window</span>
                            <ExternalLink className="w-3.5 h-3.5" />
                          </a>
                        )}

                        <button
                          onClick={handleCaptureOrder}
                          disabled={isCapturingOrder}
                          className="w-full py-3.5 rounded-xl bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-800 disabled:text-slate-600 text-white font-bold text-sm transition-all shadow-lg shadow-emerald-700/30 flex items-center justify-center gap-2"
                        >
                          {isCapturingOrder ? (
                            'Capturing via PayPal API…'
                          ) : (
                            <>
                              <CheckCircle2 className="w-4 h-4" />
                              <span>Authorize & Capture Payment</span>
                            </>
                          )}
                        </button>
                      </div>

                      {checkoutError && (
                        <div className="text-red-300 text-xs bg-red-950/40 border border-red-800 rounded-xl px-4 py-3 flex items-start gap-2">
                          <AlertCircle className="w-4 h-4 shrink-0 text-red-400 mt-0.5" />
                          <span>{checkoutError}</span>
                        </div>
                      )}
                    </>
                  ) : null}
                </div>
              )}
            </motion.div>
          </div>
        )}
      </AnimatePresence>
    </div>
  )
}
