// ═══════════════════════════════════════════════════════════
// AgentLedger — 全局类型定义（与后端 schemas/ 保持 1:1 映射）
// ═══════════════════════════════════════════════════════════

// ── 用户 & 认证 ───────────────────────────────────────────
export type UserRole = 'BOSS' | 'ACCOUNTANT' | 'DEPT_MANAGER'

export interface AuthUser {
  id: number
  display_name: string
  role: UserRole
  tenant_id: number
  account_set_id: number | null
}

export interface LoginResponse {
  access_token: string
  token_type: string
  user: AuthUser
}

// ── 凭证 ─────────────────────────────────────────────────
export type VoucherDirection = 'DEBIT' | 'CREDIT'
export type ReviewStatus = 'DRAFT' | 'PENDING_REVIEW' | 'POSTED' | 'REJECTED'

export interface VoucherLine {
  line_id?: number
  subject_code: string
  subject_name?: string
  direction: VoucherDirection
  amount: number
  memo: string | null
  auxiliary_data?: Record<string, unknown> | null
}

export interface VoucherOut {
  voucher_id: number
  voucher_date: string
  voucher_word: string
  voucher_number: number | null
  description: string
  memo: string | null
  total_debit: number
  total_credit: number
  is_balanced: boolean
  review_status: ReviewStatus
  creator_id: number | null
  created_at: string
  updated_at: string | null
  lines: VoucherLine[]
}

// ── AI 凭证 / Sprint 3.1 + 3.4 ──────────────────────────
export type ConfidenceLevel = 'HIGH' | 'MEDIUM' | 'LOW'
export type TrackSource = 'HABIT' | 'AI_RULE'

export interface VoucherDraftOut {
  memo: string
  voucher_date: string
  lines: VoucherLine[]
  total_debit: number
  total_credit: number
  is_balanced: boolean
  review_status: ReviewStatus
  circuit_breaker_triggered: boolean
  pending_review_reason: string | null
}

export interface RecommendationItem {
  track: 'A' | 'B'
  source: TrackSource
  confidence: ConfidenceLevel
  habit_rule_id: number | null
  draft: VoucherDraftOut
}

export interface DualTrackResponse {
  recommendations: RecommendationItem[]
}

export interface GenerateVoucherInput {
  description: string
  voucher_date: string
}

export interface ConfirmVoucherInput {
  description: string
  voucher_date: string
  voucher_word: string
  memo: string
  lines: VoucherLine[]
  habit_rule_id: number | null
}

// ── 习惯规则 / Sprint 3.4 + 3.6 ─────────────────────────
export interface HabitRule {
  id: number
  rule_name: string
  description: string | null
  keywords: string[]
  rule_json: Record<string, unknown>
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface HabitRuleCreateInput {
  rule_name: string
  description?: string | null
  keywords: string[]
  rule_json: Record<string, unknown>
  is_active?: boolean
}

export interface HabitRuleUpdateInput extends Partial<HabitRuleCreateInput> {}

// ── 批量导入 / Sprint 3.5 ────────────────────────────────
export type ParseEngine = 'EXCEL' | 'VISION' | 'MIXED'
export type BatchStatus = 'PENDING' | 'PROCESSING' | 'COMPLETED' | 'FAILED'

export interface StandardReceiptItem {
  date: string
  amount: number
  counterparty: string | null
  summary: string
  file_url: string | null
}

export interface ParsePreviewResponse {
  items: StandardReceiptItem[]
  total: number
  parse_engine: ParseEngine
}

export interface ExecuteBatchInput {
  items: StandardReceiptItem[]
  voucher_word: string
}

export interface ExecuteBatchResponse {
  task_id: number
  total_count: number
}

export interface TaskProgressOut {
  task_id: number
  status: BatchStatus
  total_count: number
  success_count: number
  error_count: number
  needs_review_count: number
  created_at: string
  updated_at: string | null
}

export interface BatchRecordOut {
  id: number
  raw_data: StandardReceiptItem
  confidence: ConfidenceLevel | null
  voucher_id: number | null
  needs_review: boolean
  error_msg: string | null
}

export interface BatchResultsOut {
  task_id: number
  status: BatchStatus
  success: BatchRecordOut[]
  needs_review: BatchRecordOut[]
  errors: BatchRecordOut[]
}

// ── 期间结账 / Sprint 3.3 ────────────────────────────────
export type PeriodStatus = 'OPEN' | 'CLOSED'

export interface AccountingPeriod {
  year: number
  month: number
  status: PeriodStatus
}

export interface CloseResult {
  message: string
  next_period_year: number
  next_period_month: number
  reorganized_count: number
}

export interface TransferPnLResult {
  message: string
  net_profit: number
  voucher_id: number
}

// ── 科目 ─────────────────────────────────────────────────
export type SubjectCategory = 'ASSET' | 'LIABILITY' | 'EQUITY' | 'INCOME' | 'EXPENSE'

export interface SubjectNode {
  subject_code: string
  subject_name: string
  category: SubjectCategory
  balance_direction: VoucherDirection
  is_enabled: boolean
  parent_code: string | null
  children?: SubjectNode[]
}

// ── 期初余额 ──────────────────────────────────────────────
export interface InitialBalanceNode {
  subject_code: string
  subject_name: string
  balance_direction: VoucherDirection
  opening_balance: number
  ytd_debit: number
  ytd_credit: number
  is_ai_sponge?: boolean
  children?: InitialBalanceNode[]
}

// ── Sprint 4.1 科目余额表 ─────────────────────────────────
export interface TrialBalanceItem {
  code:           string
  name:           string
  level:          number
  direction:      '借' | '贷'   // 科目固有方向
  parent_code:    string | null
  opening_debit:  number
  opening_credit: number
  current_debit:  number
  current_credit: number
  closing_debit:  number
  closing_credit: number
}

export interface TrialBalanceTotals {
  opening_debit:  number
  opening_credit: number
  current_debit:  number
  current_credit: number
  closing_debit:  number
  closing_credit: number
}

export interface TrialBalanceResponse {
  date_from:        string
  date_to:          string
  balanced:         boolean
  opening_balanced: boolean
  current_balanced: boolean
  closing_balanced: boolean
  totals:           TrialBalanceTotals
  items:            TrialBalanceItem[]
}

export interface TrialBalanceParams {
  date_from?:          string
  date_to?:            string
  max_level?:          number
  hide_zero?:          boolean
  start_subject_code?: string
  end_subject_code?:   string
}

// ── 财务工作台 ────────────────────────────────────────────
export interface WorkbenchVoucher extends VoucherOut {
  creator_name?: string
}

// ── 仪表盘统计 ────────────────────────────────────────────
export interface StatsSummary {
  total_income: number
  total_expense: number
  net_profit: number
  total_vouchers: number
  pending_review: number
}

// ── 费用申请 ──────────────────────────────────────────────
export type ExpenseStatus = 'PENDING' | 'APPROVED' | 'REJECTED'

export interface ExpenseRequest {
  request_id: number
  title: string
  amount: number
  expense_type: string
  description: string
  status: ExpenseStatus
  created_at: string
}

// ── 固定资产 ──────────────────────────────────────────────
export interface Asset {
  asset_id: number
  name: string
  original_value: number
  net_book_value: number
  status: string
  purchase_date: string
}

// ── Sprint 4.2 明细账 ─────────────────────────────────────
export interface DetailedLedgerRow {
  row_type:       'opening' | 'transaction' | 'period_total' | 'ytd_total'
  date:           string | null
  voucher_id:     number | null
  voucher_word:   string | null
  voucher_number: number | null
  subject_code:   string
  subject_name:   string
  memo:           string | null
  debit:          number
  credit:         number
  direction:      '借' | '贷' | '平' | null
  balance:        number | null
}

export interface DetailedLedgerResponse {
  subject_code: string
  date_from:    string
  date_to:      string
  rows:         DetailedLedgerRow[]
}

export interface DetailedLedgerParams {
  subject_code: string
  date_from:    string
  date_to:      string
  keyword?:     string
}

// ── Sprint 4.3 财务报表 ───────────────────────────────────
export interface BSLineItem {
  code:     string
  name:     string
  end_bal:  number
  beg_bal:  number
  is_total: boolean
}

export interface BalanceSheet {
  as_of_date:  string
  beg_of_year: string
  assets:      BSLineItem[]
  liabilities: BSLineItem[]
  equity:      BSLineItem[]
  balanced:    boolean
  diff:        number
}

export interface ISLineItem {
  code:     string
  name:     string
  cur_amt:  number
  prev_amt: number
  is_total: boolean
  row_num:  number
}

export interface IncomeStatement {
  date_from:  string
  date_to:    string
  prev_from:  string
  prev_to:    string
  items:      ISLineItem[]
  col1_label: string
  col2_label: string
}

// ── 旧账导入向导 ─────────────────────────────────────────
export type ImportSourceSystem = 'KINGDEE' | 'YONYOU' | 'GUANJIA' | 'EXCEL'

export interface ImportSession {
  session_id: number
  source_system: ImportSourceSystem
  status: string
}

export interface AbnormalSubject {
  staging_id: number
  original_code: string
  original_name: string
  suggestions: { subject_code: string; subject_name: string; confidence: number }[]
}
