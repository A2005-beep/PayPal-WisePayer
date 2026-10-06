import React, { useState } from 'react'
import { motion } from 'framer-motion'
import type { SubscriptionLeak } from '../api/wisepayerApi'

interface SubscriptionLeakDetectorProps {
  leaks: SubscriptionLeak[]
  totalAnnualWaste: number
  onCancelSubscription: (eventId: string, description: string) => void
}

const CATEGORY_EMOJI: Record<string, string> = {
  streaming: '🎬',
  gaming: '🎮',
  fitness: '🏋️',
  news: '📰',
  other: '📦',
}

const CATEGORY_COLOR: Record<string, string> = {
  streaming: 'bg-purple-900/40 border-purple-600 text-purple-200',
  gaming: 'bg-green-900/40 border-green-600 text-green-200',
  fitness: 'bg-orange-900/40 border-orange-600 text-orange-200',
  news: 'bg-blue-900/40 border-blue-600 text-blue-200',
  other: 'bg-slate-800 border-slate-600 text-slate-300',
}

export const SubscriptionLeakDetector: React.FC<SubscriptionLeakDetectorProps> = ({
  leaks,
  totalAnnualWaste,
  onCancelSubscription,
}) => {
  const [cancelling, setCancelling] = useState<string | null>(null)
  const [cancelled, setCancelled] = useState<Set<string>>(new Set())

  const handleCancel = async (leak: SubscriptionLeak) => {
    setCancelling(leak.event_id)
    await new Promise(r => setTimeout(r, 800)) // Simulate API call
    onCancelSubscription(leak.event_id, leak.description)
    setCancelled(prev => new Set(prev).add(leak.event_id))
    setCancelling(null)
  }

  const activeleaks = leaks.filter(l => !cancelled.has(l.event_id))
  const savedAnnual = leaks
    .filter(l => cancelled.has(l.event_id))
    .reduce((sum, l) => sum + l.annual_cost, 0)

  return (
    <div className="flex flex-col gap-4">
      {/* Header with waste summary */}
      <div className="flex items-center justify-between">
        <h3 className="text-white font-semibold text-base">💸 Subscription Leak Detector</h3>
        {savedAnnual > 0 && (
          <motion.span
            initial={{ scale: 0 }}
            animate={{ scale: 1 }}
            className="px-3 py-1 bg-emerald-700 text-emerald-100 rounded-full text-xs font-bold"
          >
            Saved ${savedAnnual.toFixed(0)}/yr
          </motion.span>
        )}
      </div>

      {totalAnnualWaste > 0 && (
        <div className="bg-red-900/20 border border-red-700 rounded-xl p-4 flex items-center justify-between">
          <div>
            <p className="text-red-300 text-sm font-semibold">Total Annual Subscription Waste</p>
            <p className="text-red-200 text-xs mt-0.5">
              {leaks.length} recurring charge{leaks.length !== 1 ? 's' : ''} detected
            </p>
          </div>
          <span className="text-red-300 text-2xl font-black">${totalAnnualWaste.toFixed(0)}</span>
        </div>
      )}

      {/* Leak cards */}
      <div className="flex flex-col gap-3">
        {activeleaks.length === 0 && (
          <div className="text-center py-8 text-slate-400 text-sm">
            🎉 No subscription leaks detected! Your subscriptions look clean.
          </div>
        )}
        {activeleaks.map((leak, i) => (
          <motion.div
            key={leak.event_id}
            initial={{ opacity: 0, x: -12 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: i * 0.07 }}
            className={`rounded-xl border p-4 flex items-center justify-between gap-4 ${CATEGORY_COLOR[leak.category] || CATEGORY_COLOR.other}`}
          >
            <div className="flex items-center gap-3">
              <span className="text-2xl">{CATEGORY_EMOJI[leak.category] || '📦'}</span>
              <div>
                <p className="font-semibold text-sm">{leak.description}</p>
                <p className="text-xs opacity-70">
                  ${leak.amount_per_cycle.toFixed(2)} / {leak.recurrence_days} days
                  {' · '}
                  <strong>${leak.annual_cost.toFixed(0)}/yr</strong>
                </p>
              </div>
            </div>
            <button
              onClick={() => handleCancel(leak)}
              disabled={cancelling === leak.event_id}
              className={`shrink-0 px-4 py-2 rounded-lg text-xs font-bold transition-all ${
                cancelling === leak.event_id
                  ? 'bg-slate-700 text-slate-400 cursor-wait'
                  : 'bg-red-600 hover:bg-red-500 text-white active:scale-95'
              }`}
            >
              {cancelling === leak.event_id ? 'Cancelling…' : '1-Tap Cancel'}
            </button>
          </motion.div>
        ))}
      </div>
    </div>
  )
}
