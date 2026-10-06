import React, { useEffect, useState, useMemo } from 'react'
import { AgGridReact } from 'ag-grid-react'
import type { ColDef, ICellRendererParams } from 'ag-grid-community'
import { ModuleRegistry, AllCommunityModule } from 'ag-grid-community'
import 'ag-grid-community/styles/ag-grid.css'
import 'ag-grid-community/styles/ag-theme-quartz.css'
import type { CashflowRow } from '../api/wisepayerApi'

ModuleRegistry.registerModules([AllCommunityModule])

interface CashflowGridProps {
  rows: CashflowRow[]
  currency?: string
}

const BalanceCellRenderer = (params: ICellRendererParams) => {
  const val: number = params.value ?? 0
  const color = val > 500 ? '#34d399' : val > 0 ? '#fbbf24' : '#f87171'
  return (
    <span style={{ color, fontWeight: 600 }}>
      ${val.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
    </span>
  )
}

const DirectionCellRenderer = (params: ICellRendererParams) => {
  const events = params.value as CashflowRow['events']
  if (!events || events.length === 0) return <span className="text-slate-500 text-xs">—</span>
  return (
    <div className="flex flex-col gap-0.5 py-1">
      {events.slice(0, 2).map((ev, i) => (
        <span
          key={i}
          className={`text-xs px-1.5 py-0.5 rounded ${
            ev.direction === 'inflow' ? 'bg-emerald-900 text-emerald-300' : 'bg-red-900 text-red-300'
          } ${ev.is_essential ? 'font-semibold' : ''} ${ev.is_subscription ? 'italic' : ''}`}
        >
          {ev.direction === 'inflow' ? '↑' : '↓'} {ev.description} (${ev.amount.toFixed(0)})
          {ev.is_subscription && ' 🔄'}
        </span>
      ))}
      {events.length > 2 && (
        <span className="text-xs text-slate-500">+{events.length - 2} more</span>
      )}
    </div>
  )
}

const ConfidenceBarCellRenderer = (params: ICellRendererParams) => {
  const row: CashflowRow = params.data
  if (!row) return null
  const range = row.confidence_high - row.confidence_low
  const pct = Math.min(100, Math.max(0, (range / (row.projected_balance || 1)) * 100))
  return (
    <div className="flex items-center gap-2 h-full">
      <div className="flex-1 h-2 bg-slate-700 rounded-full overflow-hidden">
        <div
          className="h-full bg-blue-500 opacity-60 rounded-full"
          style={{ width: `${100 - pct}%` }}
        />
      </div>
      <span className="text-xs text-slate-400">{(100 - pct).toFixed(0)}%</span>
    </div>
  )
}

export const CashflowGrid: React.FC<CashflowGridProps> = ({ rows, currency = 'USD' }) => {
  const colDefs = useMemo<ColDef[]>(() => [
    {
      field: 'date',
      headerName: 'Date',
      width: 120,
      pinned: 'left',
      cellClass: 'text-slate-300 font-mono text-sm',
    },
    {
      field: 'projected_balance',
      headerName: `Balance (${currency})`,
      width: 160,
      cellRenderer: BalanceCellRenderer,
      sort: null,
    },
    {
      field: 'reserved_essential',
      headerName: 'Reserved 🔒',
      width: 140,
      cellRenderer: BalanceCellRenderer,
    },
    {
      field: 'available_discretionary',
      headerName: 'Safe Discretionary 💚',
      width: 190,
      cellRenderer: BalanceCellRenderer,
    },
    {
      field: 'events',
      headerName: 'Events',
      flex: 1,
      minWidth: 240,
      cellRenderer: DirectionCellRenderer,
      autoHeight: true,
      sortable: false,
    },
    {
      headerName: 'Confidence',
      width: 140,
      cellRenderer: ConfidenceBarCellRenderer,
      sortable: false,
    },
  ], [currency])

  const defaultColDef = useMemo<ColDef>(() => ({
    sortable: true,
    resizable: true,
    filter: true,
  }), [])

  // Highlight rows where balance < 200 (danger zone)
  const getRowClass = (params: { data: CashflowRow }) => {
    if (params.data.projected_balance < 200) return 'ag-row-danger'
    if (params.data.available_discretionary === 0) return 'ag-row-warning'
    return ''
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <h3 className="text-white font-semibold text-base">📊 30-Day Cashflow Forecast</h3>
        <div className="flex gap-3 text-xs">
          <span className="flex items-center gap-1"><span className="w-3 h-3 rounded bg-emerald-500 inline-block" />Healthy</span>
          <span className="flex items-center gap-1"><span className="w-3 h-3 rounded bg-amber-500 inline-block" />Tight</span>
          <span className="flex items-center gap-1"><span className="w-3 h-3 rounded bg-red-500 inline-block" />Danger</span>
        </div>
      </div>
      <div
        className="ag-theme-quartz-dark rounded-xl overflow-hidden"
        style={{ height: 420, width: '100%' }}
      >
        <AgGridReact
          rowData={rows}
          columnDefs={colDefs}
          defaultColDef={defaultColDef}
          getRowClass={getRowClass as any}
          rowHeight={48}
          headerHeight={40}
          suppressMovableColumns={false}
          enableCellTextSelection
        />
      </div>
      <style>{`
        .ag-row-danger { background-color: rgba(239, 68, 68, 0.08) !important; }
        .ag-row-warning { background-color: rgba(245, 158, 11, 0.08) !important; }
      `}</style>
    </div>
  )
}
