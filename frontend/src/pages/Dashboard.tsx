import React, { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import { ShoppingCart, Settings, BarChart3, Repeat, Calendar } from 'lucide-react'
import { GuardianCard } from '../components/GuardianCard'
import { CashflowGrid } from '../components/CashflowGrid'
import { WiseScoreCard } from '../components/WiseScoreCard'
import { SubscriptionLeakDetector } from '../components/SubscriptionLeakDetector'
import { wisepayerApi } from '../api/wisepayerApi'
import type {
  AgentDecisionResponse,
  CashflowRow,
  WiseScoreResponse,
  SubscriptionLeak,
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

const DEMO_USER = { id: 'demo-user-001', balance: 1420, minBalance: 200 }

export const Dashboard: React.FC = () => {
  const [activeTab, setActiveTab] = useState<TabId>('checkout')

  // Checkout form state
  const [productName, setProductName] = useState('Sony WH-1000XM5 Headphones')
  const [amount, setAmount] = useState(350)
  const [autonomyLevel, setAutonomyLevel] = useState<0 | 1 | 2>(0)
  const [enableA2A, setEnableA2A] = useState(false)

  // Decision state
  const [decision, setDecision] = useState<AgentDecisionResponse | null>(null)
  const [isEvaluating, setIsEvaluating] = useState(false)
  const [evalError, setEvalError] = useState<string | null>(null)

  // Data state
  const [cashflowRows, setCashflowRows] = useState<CashflowRow[]>([])
  const [wiseScore, setWiseScore] = useState<WiseScoreResponse | null>(null)
  const [leaks, setLeaks] = useState<SubscriptionLeak[]>([])
  const [totalWaste, setTotalWaste] = useState(0)
  const [holds, setHolds] = useState<object[]>([])
  const [isLoadingData, setIsLoadingData] = useState(false)

  useEffect(() => {
    loadDashboardData()
  }, [])

  const loadDashboardData = async () => {
    setIsLoadingData(true)
    try {
      const [cashflowRes, scoreRes, leaksRes, holdsRes] = await Promise.all([
        wisepayerApi.getCashflow(DEMO_USER.id, DEMO_USER.balance, DEMO_USER.minBalance),
        wisepayerApi.getWiseScore(DEMO_USER.id, DEMO_USER.balance, DEMO_USER.minBalance),
        wisepayerApi.getSubscriptionLeaks(DEMO_USER.id, DEMO_USER.balance, DEMO_USER.minBalance),
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

  const handleEvaluate = async () => {
    setIsEvaluating(true)
    setEvalError(null)
    setDecision(null)
    try {
      const res = await wisepayerApi.evaluate({
        user_id: DEMO_USER.id,
        product_name: productName,
        amount,
        currency: 'USD',
        current_balance: DEMO_USER.balance,
        minimum_balance: DEMO_USER.minBalance,
        autonomy_level: autonomyLevel,
        merchant_agent_url: enableA2A ? 'http://localhost:8000/a2a/merchant/negotiate' : undefined,
      })
      setDecision(res.data)
    } catch (e: any) {
      setEvalError(e?.response?.data?.detail || 'Evaluation failed. Check the backend is running.')
    } finally {
      setIsEvaluating(false)
    }
  }

  return (
    <div className="min-h-screen bg-slate-950 text-white">
      {/* ── Top Nav ── */}
      <header className="border-b border-slate-800 px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center">
            <span className="text-sm">🛡️</span>
          </div>
          <div>
            <h1 className="font-bold text-lg leading-none">PayPal WisePayer</h1>
            <p className="text-xs text-slate-400">Autonomous Cashflow Guardian</p>
          </div>
        </div>
        <div className="flex items-center gap-4 text-sm text-slate-300">
          <span>Balance: <strong className="text-emerald-400">${DEMO_USER.balance.toLocaleString()}</strong></span>
          <span>Min Buffer: <strong className="text-amber-400">${DEMO_USER.minBalance}</strong></span>
          <Settings className="w-5 h-5 text-slate-500 cursor-pointer hover:text-white transition-colors" />
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
                <span className="px-1.5 py-0.5 rounded-full bg-red-600 text-white text-xs leading-none">
                  {leaks.length}
                </span>
              )}
            </button>
          ))}
        </div>
      </div>

      {/* ── Main Content ── */}
      <main className="max-w-6xl mx-auto px-6 py-8">
        {/* ── Guardian Checkout Tab ── */}
        {activeTab === 'checkout' && (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
            {/* Left: Purchase Form */}
            <div className="flex flex-col gap-6">
              <WiseScoreCard scoreData={wiseScore} isLoading={isLoadingData} />

              <div className="bg-slate-800 border border-slate-700 rounded-2xl p-6 flex flex-col gap-5">
                <h2 className="text-white font-semibold">🛒 Evaluate a Purchase</h2>

                <div>
                  <label className="text-xs text-slate-400 mb-1 block">Product Name</label>
                  <input
                    value={productName}
                    onChange={e => setProductName(e.target.value)}
                    className="w-full bg-slate-700 border border-slate-600 rounded-xl px-4 py-3 text-white text-sm focus:outline-none focus:border-blue-500"
                    placeholder="What do you want to buy?"
                  />
                </div>

                <div>
                  <label className="text-xs text-slate-400 mb-1 block">Amount (USD)</label>
                  <input
                    type="number"
                    value={amount}
                    onChange={e => setAmount(Number(e.target.value))}
                    className="w-full bg-slate-700 border border-slate-600 rounded-xl px-4 py-3 text-white text-sm focus:outline-none focus:border-blue-500"
                    min={1}
                  />
                </div>

                {/* Autonomy Ladder */}
                <div>
                  <label className="text-xs text-slate-400 mb-2 block">Autonomy Level</label>
                  <div className="flex flex-col gap-2">
                    {AUTONOMY_OPTIONS.map(opt => (
                      <button
                        key={opt.value}
                        onClick={() => setAutonomyLevel(opt.value as 0 | 1 | 2)}
                        className={`flex items-center gap-3 px-4 py-3 rounded-xl border text-left transition-all ${
                          autonomyLevel === opt.value
                            ? 'border-blue-500 bg-blue-900/30'
                            : 'border-slate-600 bg-slate-700/50 hover:border-slate-500'
                        }`}
                      >
                        <span className="text-sm font-semibold text-white">{opt.label}</span>
                        <span className="text-xs text-slate-400">{opt.desc}</span>
                      </button>
                    ))}
                  </div>
                </div>

                {/* A2A Toggle */}
                <div className="flex items-center justify-between py-2 px-4 bg-purple-900/20 border border-purple-700 rounded-xl">
                  <div>
                    <p className="text-sm text-purple-200 font-semibold">🤝 A2A Merchant Negotiation</p>
                    <p className="text-xs text-purple-400">Buyer Agent will negotiate price with Merchant Agent</p>
                  </div>
                  <button
                    onClick={() => setEnableA2A(!enableA2A)}
                    className={`w-12 h-6 rounded-full transition-colors ${enableA2A ? 'bg-purple-600' : 'bg-slate-600'} relative`}
                  >
                    <div className={`w-5 h-5 rounded-full bg-white absolute top-0.5 transition-all ${enableA2A ? 'left-6' : 'left-0.5'}`} />
                  </button>
                </div>

                <button
                  onClick={handleEvaluate}
                  disabled={isEvaluating || !productName || amount <= 0}
                  className="w-full py-4 rounded-xl bg-blue-600 hover:bg-blue-500 disabled:bg-slate-700 disabled:text-slate-500 text-white font-bold text-sm transition-all active:scale-98"
                >
                  {isEvaluating ? '⚡ Agent Analyzing…' : '🛡️ Ask WisePayer Guardian'}
                </button>

                {evalError && (
                  <div className="text-red-400 text-sm bg-red-900/20 border border-red-700 rounded-xl px-4 py-3">
                    {evalError}
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
                  onConfirmPayment={() => alert(`✅ Payment initiated via PayPal!\nOrder ID: ${decision?.paypal_order_id || 'demo-order-' + Date.now()}`)}
                  onReject={() => setDecision(null)}
                  isLoading={isEvaluating}
                />
              ) : (
                <div className="rounded-2xl border border-dashed border-slate-700 bg-slate-800/30 flex flex-col items-center justify-center p-12 gap-4 text-center h-full min-h-64">
                  <span className="text-5xl">🛡️</span>
                  <p className="text-slate-400 text-sm max-w-xs">
                    Enter a product and click <strong className="text-white">Ask WisePayer Guardian</strong> to see the full cashflow analysis and decision.
                  </p>
                </div>
              )}
            </div>
          </div>
        )}

        {/* ── Cashflow Tab (AG Grid) ── */}
        {activeTab === 'cashflow' && (
          <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
            {isLoadingData ? (
              <div className="text-slate-400 text-sm py-20 text-center">Loading cashflow data…</div>
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
              onCancelSubscription={(id) => {
                console.log('Cancelling subscription:', id)
                // In production: call wisepayerApi.cancelSubscription(id)
              }}
            />
          </motion.div>
        )}

        {/* ── Smart Holds Tab (Bryntum integration note) ── */}
        {activeTab === 'holds' && (
          <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="flex flex-col gap-4">
            <h3 className="text-white font-semibold text-base">📅 Smart Wait Holds</h3>
            <div className="bg-blue-900/20 border border-blue-700 rounded-xl p-4 text-sm text-blue-200">
              <strong>Bryntum Scheduler Integration:</strong> This tab renders a Bryntum Scheduler timeline 
              showing pending smart-wait holds. Each hold shows the purchase, amount, and the safe execution date 
              (salary arrival milestone). The Bryntum component requires a commercial license — 
              see <code className="bg-blue-900 px-1 rounded">frontend/src/components/SmartWaitTimeline.tsx</code>.
            </div>
            {holds.length === 0 ? (
              <div className="text-center py-16 text-slate-400 text-sm">
                No smart-wait holds active. They appear here when WisePayer defers a purchase.
              </div>
            ) : (
              <div className="flex flex-col gap-3">
                {(holds as any[]).map((hold, i) => (
                  <div key={i} className="bg-slate-800 border border-slate-700 rounded-xl p-4 flex items-center justify-between">
                    <div>
                      <p className="text-white font-semibold text-sm">{hold.product_name}</p>
                      <p className="text-slate-400 text-xs mt-0.5">
                        ${hold.amount} · Execute on {hold.execute_date}
                      </p>
                    </div>
                    <span className="px-3 py-1 bg-blue-700 text-blue-100 rounded-full text-xs font-semibold">
                      Pending
                    </span>
                  </div>
                ))}
              </div>
            )}
          </motion.div>
        )}
      </main>
    </div>
  )
}
