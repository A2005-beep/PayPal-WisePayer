import React, { useState } from 'react'
import { motion } from 'framer-motion'
import type { WiseScoreResponse } from '../api/wisepayerApi'

interface WiseScoreCardProps {
  scoreData: WiseScoreResponse | null
  isLoading?: boolean
}

const gradeColor: Record<string, string> = {
  'A+': 'text-emerald-400',
  'A': 'text-emerald-400',
  'B': 'text-green-400',
  'C': 'text-amber-400',
  'D': 'text-orange-400',
  'F': 'text-red-400',
}

const scoreToColor = (score: number) => {
  if (score >= 80) return 'from-emerald-500 to-green-400'
  if (score >= 60) return 'from-amber-500 to-yellow-400'
  return 'from-red-500 to-orange-400'
}

export const WiseScoreCard: React.FC<WiseScoreCardProps> = ({ scoreData, isLoading }) => {
  const [showInsights, setShowInsights] = useState(true)

  if (isLoading) {
    return (
      <div className="rounded-2xl bg-slate-800 border border-slate-700 p-6 flex items-center justify-center h-40">
        <div className="animate-pulse text-slate-400 text-sm">Computing WiseScore…</div>
      </div>
    )
  }

  if (!scoreData) return null

  const circumference = 2 * Math.PI * 54
  const dashOffset = circumference * (1 - scoreData.score / 100)

  return (
    <div className="rounded-2xl bg-slate-800 border border-slate-700 p-6 flex flex-col gap-5">
      <div className="flex items-center justify-between">
        <h3 className="text-white font-semibold text-base">🛡️ WiseScore</h3>
        <span className={`text-3xl font-black ${gradeColor[scoreData.grade] || 'text-white'}`}>
          {scoreData.grade}
        </span>
      </div>

      {/* Circular progress */}
      <div className="flex items-center justify-center">
        <div className="relative w-32 h-32">
          <svg className="w-32 h-32 -rotate-90" viewBox="0 0 120 120">
            <circle cx="60" cy="60" r="54" fill="none" stroke="#1e293b" strokeWidth="10" />
            <motion.circle
              cx="60"
              cy="60"
              r="54"
              fill="none"
              stroke="url(#scoreGrad)"
              strokeWidth="10"
              strokeLinecap="round"
              strokeDasharray={circumference}
              initial={{ strokeDashoffset: circumference }}
              animate={{ strokeDashoffset: dashOffset }}
              transition={{ duration: 1.2, ease: 'easeOut' }}
            />
            <defs>
              <linearGradient id="scoreGrad" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" stopColor={scoreData.score >= 60 ? '#10b981' : '#ef4444'} />
                <stop offset="100%" stopColor={scoreData.score >= 80 ? '#34d399' : scoreData.score >= 60 ? '#fbbf24' : '#f97316'} />
              </linearGradient>
            </defs>
          </svg>
          <div className="absolute inset-0 flex flex-col items-center justify-center">
            <motion.span
              initial={{ opacity: 0, scale: 0.5 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ delay: 0.5 }}
              className={`text-3xl font-black bg-gradient-to-r ${scoreToColor(scoreData.score)} bg-clip-text text-transparent`}
            >
              {scoreData.score}
            </motion.span>
            <span className="text-xs text-slate-400">/ 100</span>
          </div>
        </div>
      </div>

      {/* Metrics row */}
      <div className="grid grid-cols-3 gap-3 text-center">
        <div className="bg-slate-700/50 rounded-xl p-3">
          <p className="text-lg font-bold text-white">
            {(scoreData.liquidity_ratio * 100).toFixed(0)}%
          </p>
          <p className="text-xs text-slate-400 mt-0.5">Liquidity</p>
        </div>
        <div className={`rounded-xl p-3 ${scoreData.overdraft_risk_days > 0 ? 'bg-red-900/30' : 'bg-slate-700/50'}`}>
          <p className={`text-lg font-bold ${scoreData.overdraft_risk_days > 0 ? 'text-red-400' : 'text-white'}`}>
            {scoreData.overdraft_risk_days}d
          </p>
          <p className="text-xs text-slate-400 mt-0.5">Risk Days</p>
        </div>
        <div className={`rounded-xl p-3 ${scoreData.subscription_waste_annual > 300 ? 'bg-orange-900/30' : 'bg-slate-700/50'}`}>
          <p className={`text-lg font-bold ${scoreData.subscription_waste_annual > 300 ? 'text-orange-400' : 'text-white'}`}>
            ${scoreData.subscription_waste_annual.toFixed(0)}
          </p>
          <p className="text-xs text-slate-400 mt-0.5">Sub Waste/yr</p>
        </div>
      </div>

      {/* Insights */}
      {scoreData.insights.length > 0 && (
        <div>
          <button
            onClick={() => setShowInsights(!showInsights)}
            className="text-xs text-slate-400 hover:text-white transition-colors mb-2"
          >
            {showInsights ? '▾ Hide' : '▸ Show'} Insights ({scoreData.insights.length})
          </button>
          {showInsights && (
            <div className="flex flex-col gap-2">
              {scoreData.insights.map((insight, i) => (
                <motion.div
                  key={i}
                  initial={{ opacity: 0, y: 4 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: i * 0.08 }}
                  className="text-sm text-slate-200 bg-slate-700/40 rounded-lg px-3 py-2"
                >
                  {insight}
                </motion.div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
