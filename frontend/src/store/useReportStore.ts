import { create } from 'zustand'
import type {
  TrialBalanceItem, TrialBalanceTotals, TrialBalanceParams,
  DetailedLedgerRow,
} from '@/types'

// ── 默认期间：当月 ────────────────────────────────────────────────────────────
function defaultDateFrom(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-01`
}
function defaultDateTo(): string {
  const d = new Date()
  return d.toISOString().slice(0, 10)
}

interface ReportState {
  // ── 科目余额表筛选条件 ──────────────────────────────────────
  tbParams: TrialBalanceParams

  // ── 科目余额表数据 ─────────────────────────────────────────
  tbItems:           TrialBalanceItem[]
  tbTotals:          TrialBalanceTotals | null
  tbBalanced:        boolean
  tbOpeningBalanced: boolean
  tbCurrentBalanced: boolean
  tbClosingBalanced: boolean
  tbLoading:         boolean
  tbError:           string | null

  // ── 明细账数据（Sprint 4.2） ───────────────────────────────
  dlRows:    DetailedLedgerRow[]
  dlLoading: boolean
  dlError:   string | null

  // ── Actions ────────────────────────────────────────────────
  setTbParams:  (p: Partial<TrialBalanceParams>) => void
  setTbData:    (items: TrialBalanceItem[], totals: TrialBalanceTotals, balanced: boolean, ob: boolean, cb: boolean, clb: boolean) => void
  setTbLoading: (v: boolean) => void
  setTbError:   (e: string | null) => void
  resetTb:      () => void

  setDlRows:    (rows: DetailedLedgerRow[]) => void
  setDlLoading: (v: boolean) => void
  setDlError:   (e: string | null) => void
  resetDl:      () => void
}

const defaultTotals: TrialBalanceTotals = {
  opening_debit: 0, opening_credit: 0,
  current_debit: 0, current_credit: 0,
  closing_debit: 0, closing_credit: 0,
}

export const useReportStore = create<ReportState>((set) => ({
  tbParams: {
    date_from: defaultDateFrom(),
    date_to:   defaultDateTo(),
    hide_zero: false,
  },
  tbItems:           [],
  tbTotals:          null,
  tbBalanced:        true,
  tbOpeningBalanced: true,
  tbCurrentBalanced: true,
  tbClosingBalanced: true,
  tbLoading:         false,
  tbError:           null,

  dlRows:    [],
  dlLoading: false,
  dlError:   null,

  setTbParams: (p) =>
    set((s) => ({ tbParams: { ...s.tbParams, ...p } })),

  setTbData: (items, totals, balanced, ob, cb, clb) =>
    set({
      tbItems:           items,
      tbTotals:          totals,
      tbBalanced:        balanced,
      tbOpeningBalanced: ob,
      tbCurrentBalanced: cb,
      tbClosingBalanced: clb,
      tbError:           null,
    }),

  setTbLoading: (v) => set({ tbLoading: v }),
  setTbError:   (e) => set({ tbError: e, tbLoading: false }),

  resetTb: () =>
    set({
      tbItems:    [],
      tbTotals:   defaultTotals,
      tbBalanced: true,
      tbError:    null,
    }),

  setDlRows:    (rows) => set({ dlRows: rows, dlError: null }),
  setDlLoading: (v)    => set({ dlLoading: v }),
  setDlError:   (e)    => set({ dlError: e, dlLoading: false }),
  resetDl:      ()     => set({ dlRows: [], dlError: null }),
}))
