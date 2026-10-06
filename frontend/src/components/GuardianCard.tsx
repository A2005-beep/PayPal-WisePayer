import React, { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { ShieldCheck, AlertTriangle, XCircle, Clock, Zap, ChevronDown, ChevronUp } from 'lucide-react'
import type { AgentDecisionResponse } from '../api/wisepayerApi'

interface GuardianCardProps {
  decision: AgentDecisionResponse | null
  productName: string
  requestedAmount: number
  currentBalance: number
  onConfirmPayment: () => void
  onReject: () => void
  isLoading: boolean
}

const STATUS_CONFIG = {
  affordable_now: {
    icon: ShieldCheck,
    color: 'text-emerald-400',
    bg: 'bg-emerald-900/30 border-emerald-700',
    badge: 'bg-emerald-500',
    label: '✅ Safe to Purchase',
  },
  affordable_with_plan: {
    icon: Zap,
    color: 'text-amber-400',
    bg: 'bg-amber-900/30 border-amber-700',
    badge: 'bg-amber-500',
    label: '💡 Affordable with Plan',
  },
  affordable_later: {
    icon: Clock,
    color: 'text-blue-400',
    bg: 'bg-blue-900/30 border-blue-700',
    badge: 'bg-blue-500',
    label: '⏳ Affordable Later',
  },
  not_affordable: {
    icon: XCircle,
    color: 'text-red-400',
    bg: 'bg-red-900/30 border-red-700',
    badge: 'bg-red-500',
    label: '🛑 Not Recommended',
  },
}

const ACTION_LABELS: Record<string, string> = {
  full_payment: 'Pay Full Amount via PayPal',
  pay_in_4: 'Pay in 4 via PayPal',
  smart_wait: 'Activate Smart Wait Hold',
  not_recommended: 'No Safe Option Available',
}

export const GuardianCard: React.FC<GuardianCardProps> = ({
  decision,
  productName,
  requestedAmount,
  currentBalance,
  onConfirmPayment,
  onReject,
  isLoading,
}) => {
  const [showDetails, setShowDetails] = useState(false)

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center p-8 rounded-2xl bg-slate-800 border border-slate-700 gap-4">
        <motion.div
          animate={{ rotate: 360 }}
          transition={{ duration: 1.5, repeat: Infinity, ease: 'linear' }}
          className="w-12 h-12 rounded-full border-4 border-blue-500 border-t-transparent"
        />
        <p className="text-slate-300 text-sm">WisePayer agent analyzing your cashflow…</p>
      </div>
    )
  }

  if (!decision) return null

  const config = STATUS_CONFIG[decision.affordability_status]
  const StatusIcon = config.icon
  const reservedAmount = currentBalance - decision.safe_to_pay_today
  const canExecute = decision.recommended_action !== 'not_recommended'

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0, y: 20, scale: 0.97 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: -20 }}
        transition={{ duration: 0.35, ease: 'easeOut' }}
        className={`rounded-2xl border p-6 flex flex-col gap-5 shadow-2xl ${config.bg}`}
      >
        {/* ── Header ── */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <StatusIcon className={`w-7 h-7 ${config.color}`} />
            <div>
              <p className="text-xs text-slate-400 uppercase tracking-wider">WisePayer Guardian</p>
              <h2 className={`text-lg font-bold ${config.color}`}>{config.label}</h2>
            </div>
          </div>
          {/* WiseScore badge */}
          <div className="flex flex-col items-center">
            <div className={`w-14 h-14 rounded-full flex items-center justify-center text-white font-black text-xl ${config.badge}`}>
              {decision.wise_score}
            </div>
            <span className="text-xs text-slate-400 mt-1">WiseScore</span>
          </div>
        </div>

        {/* ── Liquidity Gauge ── */}
        <div className="flex flex-col gap-2">
          <div className="flex justify-between text-xs text-slate-400">
            <span>Total Balance</span>
            <span className="font-semibold text-white">${currentBalance.toLocaleString()}</span>
          </div>
          <div className="w-full h-4 bg-slate-700 rounded-full overflow-hidden flex">
            {/* Reserved essential */}
            <motion.div
              initial={{ width: 0 }}
              animate={{ width: `${Math.min(100, (reservedAmount / currentBalance) * 100)}%` }}
              transition={{ duration: 0.6, ease: 'easeOut' }}
              className="h-full bg-red-500 opacity-80"
              title={`Reserved: $${reservedAmount.toFixed(2)}`}
            />
            {/* Safe discretionary */}
            <motion.div
              initial={{ width: 0 }}
              animate={{ width: `${Math.min(100, (decision.safe_to_pay_today / currentBalance) * 100)}%` }}
              transition={{ duration: 0.6, delay: 0.1, ease: 'easeOut' }}
              className="h-full bg-emerald-500"
              title={`Safe Discretionary: $${decision.safe_to_pay_today.toFixed(2)}`}
            />
          </div>
          <div className="flex justify-between text-xs">
            <span className="text-red-400">🔒 Reserved: ${reservedAmount.toFixed(2)}</span>
            <span className="text-emerald-400">💚 Safe: ${decision.safe_to_pay_today.toFixed(2)}</span>
          </div>
        </div>

        {/* ── Explain My No ── */}
        <div className="bg-slate-900/60 rounded-xl p-4 text-sm text-slate-200 leading-relaxed border border-slate-700">
          {decision.explain_my_no}
        </div>

        {/* ── Negotiation Banner ── */}
        {decision.negotiated_amount && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="bg-purple-900/40 border border-purple-600 rounded-xl p-3 text-sm text-purple-200 flex items-center gap-2"
          >
            <Zap className="w-4 h-4 text-purple-400 shrink-0" />
            <span>
              🤝 <strong>A2A Negotiation</strong>: Merchant agent agreed on{' '}
              <strong>${decision.negotiated_amount.toFixed(2)}</strong>{' '}
              (saved ${(requestedAmount - decision.negotiated_amount).toFixed(2)})
            </span>
          </motion.div>
        )}

        {/* ── Payment Plan (collapsible) ── */}
        {decision.payment_plan.length > 0 && (
          <div>
            <button
              onClick={() => setShowDetails(!showDetails)}
              className="flex items-center gap-2 text-sm text-slate-300 hover:text-white transition-colors"
            >
              {showDetails ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
              {showDetails ? 'Hide' : 'Show'} Payment Schedule
            </button>
            <AnimatePresence>
              {showDetails && (
                <motion.div
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: 'auto', opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  className="mt-3 overflow-hidden"
                >
                  <div className="flex flex-col gap-2">
                    {decision.payment_plan.map((p, i) => (
                      <div key={i} className="flex justify-between items-center bg-slate-800 rounded-lg px-4 py-2 text-sm">
                        <span className="text-slate-400">{p.date}</span>
                        <span className="font-semibold text-white">${p.amount.toFixed(2)}</span>
                        {i === 0 && decision.recommended_action === 'pay_in_4' && (
                          <span className="text-xs bg-blue-600 text-white px-2 py-0.5 rounded-full">Today</span>
                        )}
                      </div>
                    ))}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        )}

        {/* ── Smart Wait Earliest Date ── */}
        {decision.earliest_safe_date && decision.recommended_action === 'smart_wait' && (
          <div className="flex items-center gap-2 text-sm text-blue-300 bg-blue-900/30 rounded-lg px-4 py-2 border border-blue-700">
            <Clock className="w-4 h-4 shrink-0" />
            <span>
              WisePayer will auto-execute on{' '}
              <strong>{decision.earliest_safe_date}</strong> when cashflow is safe.
            </span>
          </div>
        )}

        {/* ── Autonomy Level Badge ── */}
        <div className="flex items-center gap-2 text-xs text-slate-400">
          <span>Autonomy Mode:</span>
          <span className={`px-2 py-0.5 rounded-full font-semibold ${
            decision.autonomy_level === 'ADVISE' ? 'bg-slate-700 text-slate-300' :
            decision.autonomy_level === 'BOUNDED' ? 'bg-amber-800 text-amber-200' :
            'bg-red-900 text-red-200'
          }`}>
            {decision.autonomy_level === 'ADVISE' ? '🟢 Advise' :
             decision.autonomy_level === 'BOUNDED' ? '🟡 Bounded' : '🔴 Full Guardian'}
          </span>
          {decision.rollback_deadline && (
            <span className="text-orange-400">
              • Rollback window until {new Date(decision.rollback_deadline).toLocaleTimeString()}
            </span>
          )}
        </div>

        {/* ── Action Buttons ── */}
        <div className="flex gap-3 pt-1">
          <button
            onClick={onReject}
            className="flex-1 py-3 rounded-xl bg-slate-700 hover:bg-slate-600 text-slate-200 text-sm font-medium transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={onConfirmPayment}
            disabled={!canExecute}
            className={`flex-[2] py-3 rounded-xl text-white text-sm font-bold transition-all ${
              canExecute
                ? 'bg-blue-600 hover:bg-blue-500 active:scale-95 shadow-lg shadow-blue-900/50'
                : 'bg-slate-700 text-slate-500 cursor-not-allowed'
            }`}
          >
            {ACTION_LABELS[decision.recommended_action]}
          </button>
        </div>
      </motion.div>
    </AnimatePresence>
  )
}
