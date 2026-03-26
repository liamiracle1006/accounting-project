-- ============================================================
-- AgentLedger V2.0 — DDL
-- Database: MySQL 8+ / PostgreSQL 14+
-- ============================================================

-- ------------------------------------------------------------
-- 1. 会计科目表 (Account Subject)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS account_subject (
    subject_code  VARCHAR(10)  NOT NULL,          -- e.g. '1002', '6602'
    subject_name  VARCHAR(100) NOT NULL,           -- e.g. '银行存款', '销售费用'
    subject_type  VARCHAR(20)  NOT NULL,           -- 资产/负债/权益/收入/费用
    direction     VARCHAR(10)  NOT NULL,           -- DEBIT=借方增加 / CREDIT=贷方增加
    is_active     TINYINT(1)   NOT NULL DEFAULT 1,
    created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (subject_code)
);

-- ------------------------------------------------------------
-- 2. 辅助核算表 (Auxiliary Entity)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS auxiliary_entity (
    entity_id   BIGINT       NOT NULL AUTO_INCREMENT,
    entity_type VARCHAR(20)  NOT NULL,             -- 员工/部门/客户/供应商
    entity_name VARCHAR(100) NOT NULL,
    is_active   TINYINT(1)   NOT NULL DEFAULT 1,
    created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (entity_id)
);

-- ------------------------------------------------------------
-- 3. 企业税收画像表 (Enterprise Profile) — 系统参数中枢
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS enterprise_profile (
    company_id                  BIGINT          NOT NULL AUTO_INCREMENT,
    company_name                VARCHAR(200)    NOT NULL,
    company_type                VARCHAR(20)     NOT NULL DEFAULT 'MICRO',
                                                         -- MICRO=小微/个体户, STANDARD=一般企业
    industry_code               VARCHAR(50)     NOT NULL DEFAULT '通用',
                                                         -- 制造业/软件服务业/批发零售业/餐饮住宿业/建筑业/通用
    tax_payer_type              VARCHAR(20)     NOT NULL DEFAULT 'SMALL_SCALE',
                                                         -- SMALL_SCALE=小规模纳税人, GENERAL=一般纳税人
    applicable_income_tax_rate  DECIMAL(5, 4)   NOT NULL DEFAULT 0.2000,
                                                         -- 企业所得税率: 0.25/0.20/0.15/0.05
    vat_rate                    DECIMAL(5, 4)   NOT NULL DEFAULT 0.0300,
                                                         -- 增值税率: 0.03/0.05/0.06/0.09/0.13
    decision_threshold          DECIMAL(18, 2)  NOT NULL DEFAULT 5000.00,
                                                         -- 老板决策触发阈值（元）
    accounting_standard         VARCHAR(20)     NOT NULL DEFAULT 'SMALL_BIZ',
                                                         -- SMALL_BIZ=小企业会计准则, GENERAL=企业会计准则
    is_active                   TINYINT(1)      NOT NULL DEFAULT 1,
                                                         -- 1=当前激活，系统同时只有一条激活记录
    created_at                  DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at                  DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP
                                                ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (company_id)
);

-- ------------------------------------------------------------
-- 4. 业务流水表 (Operational Record) — AI 缓冲池
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS operational_record (
    record_id      BIGINT       NOT NULL AUTO_INCREMENT,
    raw_text       TEXT         NOT NULL,           -- 原始自然语言输入
    extracted_json TEXT         NULL,               -- LLM 返回的 JSON
    status         VARCHAR(30)  NOT NULL DEFAULT 'PENDING',
                                                    -- PENDING / PROCESSED / PENDING_BOSS_DECISION / MANUAL_REVIEW
    error_message  TEXT         NULL,               -- 失败原因 / 拦截说明
    created_at     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
                                ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (record_id)
);

-- ------------------------------------------------------------
-- 5. 凭证主表 (Voucher Header)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS voucher_header (
    voucher_id    BIGINT         NOT NULL AUTO_INCREMENT,
    record_id     BIGINT         NOT NULL,           -- FK → operational_record
    voucher_date  DATE           NOT NULL,
    total_amount  DECIMAL(18, 2) NOT NULL,
    memo          VARCHAR(500)   NULL,
    review_status VARCHAR(20)    NOT NULL DEFAULT 'DRAFT',
                                                     -- DRAFT / PENDING_REVIEW / POSTED / REJECTED
    reviewer_id   BIGINT         NULL,               -- FK → user_account
    review_note   VARCHAR(500)   NULL,
    reviewed_at   DATETIME       NULL,
    created_at    DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (voucher_id),
    CONSTRAINT fk_vh_record FOREIGN KEY (record_id)
        REFERENCES operational_record (record_id)
);

-- ------------------------------------------------------------
-- 6. 凭证明细表 (Voucher Line)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS voucher_line (
    line_id             BIGINT         NOT NULL AUTO_INCREMENT,
    voucher_id          BIGINT         NOT NULL,    -- FK → voucher_header
    subject_code        VARCHAR(10)    NOT NULL,    -- FK → account_subject
    direction           VARCHAR(10)    NOT NULL,    -- DEBIT / CREDIT
    amount              DECIMAL(18, 2) NOT NULL,
    auxiliary_entity_id BIGINT         NULL,        -- FK → auxiliary_entity (可为空)
    memo                VARCHAR(200)   NULL,
    PRIMARY KEY (line_id),
    CONSTRAINT fk_vl_voucher  FOREIGN KEY (voucher_id)
        REFERENCES voucher_header (voucher_id),
    CONSTRAINT fk_vl_subject  FOREIGN KEY (subject_code)
        REFERENCES account_subject (subject_code),
    CONSTRAINT fk_vl_entity   FOREIGN KEY (auxiliary_entity_id)
        REFERENCES auxiliary_entity (entity_id),
    CONSTRAINT chk_direction  CHECK (direction IN ('DEBIT', 'CREDIT')),
    CONSTRAINT chk_amount_pos CHECK (amount > 0)
);

-- ------------------------------------------------------------
-- 7. Boss Decision Log — intercept record awaiting boss choice
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS boss_decision_log (
    decision_id         BIGINT       NOT NULL AUTO_INCREMENT,
    record_id           BIGINT       NOT NULL,           -- FK → operational_record
    ai_options_json     TEXT         NOT NULL,           -- full JSON: options[], recommendation, snapshot
    boss_choice         VARCHAR(50)  NULL,               -- chosen option id (e.g. ONE_TIME)
    chosen_action_code  VARCHAR(50)  NULL,               -- action_code of chosen option
    status              VARCHAR(30)  NOT NULL DEFAULT 'PENDING_DECISION',
                                                         -- PENDING_DECISION / DECIDED / EXPIRED
    expires_at          DATETIME     NULL,               -- auto-expire after N days
    decided_at          DATETIME     NULL,
    created_at          DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (decision_id),
    CONSTRAINT fk_bdl_record FOREIGN KEY (record_id)
        REFERENCES operational_record (record_id)
);

-- ------------------------------------------------------------
-- 8. Asset Register — fixed asset ledger with depreciation
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS asset_register (
    asset_id                    BIGINT          NOT NULL AUTO_INCREMENT,
    voucher_id                  BIGINT          NOT NULL,  -- FK → voucher_header
    decision_id                 BIGINT          NULL,      -- FK → boss_decision_log
    asset_name                  VARCHAR(200)    NOT NULL,
    asset_category              VARCHAR(50)     NOT NULL DEFAULT '通用设备',
                                                           -- 电子设备/通用机械/车辆/建筑装修/通用设备
    original_value              DECIMAL(18, 2)  NOT NULL,
    net_salvage_value           DECIMAL(18, 2)  NOT NULL DEFAULT 0.00,
    depreciation_method         VARCHAR(20)     NOT NULL,
                                                           -- STRAIGHT_LINE / ACCELERATED / ONE_TIME
    useful_life_months          INT             NOT NULL,
    monthly_depreciation        DECIMAL(18, 2)  NOT NULL,
    accumulated_depreciation    DECIMAL(18, 2)  NOT NULL DEFAULT 0.00,
    depreciation_months_elapsed INT             NOT NULL DEFAULT 0,
    status                      VARCHAR(20)     NOT NULL DEFAULT 'IN_USE',
                                                           -- IN_USE / FULLY_DEPRECIATED / DISPOSED
    purchase_date               DATE            NOT NULL,
    depreciation_start_month    VARCHAR(7)      NOT NULL,  -- YYYY-MM, starts next month after purchase
    notes                       TEXT            NULL,
    created_at                  DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at                  DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP
                                                ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (asset_id),
    CONSTRAINT fk_ar_voucher  FOREIGN KEY (voucher_id)
        REFERENCES voucher_header (voucher_id),
    CONSTRAINT fk_ar_decision FOREIGN KEY (decision_id)
        REFERENCES boss_decision_log (decision_id)
);

-- ------------------------------------------------------------
-- 9. Department — cost center (Phase 3)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS department (
    dept_id     BIGINT      NOT NULL AUTO_INCREMENT,
    dept_name   VARCHAR(100) NOT NULL UNIQUE,
    cost_center VARCHAR(50)  NULL,               -- 成本中心代码（可选）
    manager_id  BIGINT       NULL,               -- FK → user_account.user_id
    is_active   TINYINT(1)   NOT NULL DEFAULT 1,
    created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
                             ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (dept_id)
);

-- ------------------------------------------------------------
-- 10. Expense Request — approval workflow (Phase 3)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS expense_request (
    request_id   BIGINT         NOT NULL AUTO_INCREMENT,
    applicant_id BIGINT         NOT NULL,           -- FK → user_account
    dept_id      BIGINT         NULL,               -- FK → department
    title        VARCHAR(200)   NOT NULL,
    amount       DECIMAL(18, 2) NOT NULL,
    expense_type VARCHAR(100)   NOT NULL,           -- 差旅/办公/采购/其他
    description  TEXT           NULL,
    status       VARCHAR(20)    NOT NULL DEFAULT 'PENDING',
                                                    -- PENDING / APPROVED / REJECTED
    reviewer_id  BIGINT         NULL,               -- FK → user_account
    review_note  TEXT           NULL,
    reviewed_at  DATETIME       NULL,
    record_id    BIGINT         NULL,               -- FK → operational_record (审批通过后填入)
    created_at   DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at   DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP
                                ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (request_id)
);

-- ------------------------------------------------------------
-- 11. User Account — multi-role login (Phase 3)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS user_account (
    user_id       BIGINT       NOT NULL AUTO_INCREMENT,
    username      VARCHAR(50)  NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,               -- bcrypt hash
    display_name  VARCHAR(100) NOT NULL,
    role          VARCHAR(20)  NOT NULL DEFAULT 'ACCOUNTANT',
                                                       -- BOSS / ACCOUNTANT / DEPT_MANAGER
    department_id BIGINT       NULL,                   -- FK → department (added in task 3)
    is_active     TINYINT(1)   NOT NULL DEFAULT 1,
    last_login_at DATETIME     NULL,
    created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
                               ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id)
);

-- ------------------------------------------------------------
-- 12. Accounting Period — month-end close tracking (Phase 4)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS accounting_period (
    period_id          BIGINT    NOT NULL AUTO_INCREMENT,
    year               INT       NOT NULL,
    month              INT       NOT NULL,             -- 1-12
    status             VARCHAR(10) NOT NULL DEFAULT 'OPEN',
                                                       -- OPEN / CLOSED
    closed_at          DATETIME  NULL,
    closed_by          BIGINT    NULL,                 -- FK → user_account
    closing_voucher_id BIGINT    NULL,                 -- FK → voucher_header
    created_at         DATETIME  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (period_id),
    UNIQUE KEY uq_period_ym (year, month)
);
