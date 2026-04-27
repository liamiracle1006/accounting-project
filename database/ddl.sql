-- ============================================================
-- AgentLedger V4.0 — DDL
-- Database: MySQL 8+
-- Breaking change: DROP old V3.0 tables before running this in dev.
-- All business tables now carry tenant_id + account_set_id.
-- ============================================================

-- ------------------------------------------------------------
-- 0. Shared system tables (no tenant isolation)
-- ------------------------------------------------------------

-- 0a. Account Subject — standard Chinese chart of accounts (shared)
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
-- 1. Tenant — top-level SaaS tenant
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tenant (
    tenant_id     BIGINT       NOT NULL AUTO_INCREMENT,
    tenant_name   VARCHAR(200) NOT NULL,
    contact_email VARCHAR(200) NULL,
    status        VARCHAR(20)  NOT NULL DEFAULT 'TRIAL',
                                                   -- TRIAL / ACTIVE / SUSPENDED
    created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
                               ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id)
);

-- ------------------------------------------------------------
-- 2. Account Set — 账套 (a tenant can have multiple books)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS account_set (
    account_set_id          BIGINT      NOT NULL AUTO_INCREMENT,
    tenant_id               BIGINT      NOT NULL,              -- FK → tenant
    account_set_name        VARCHAR(200) NOT NULL,
    fiscal_year_start_month INT         NOT NULL DEFAULT 1,    -- 1=January
    accounting_standard     VARCHAR(20) NOT NULL DEFAULT 'SMALL_BIZ',
                                                               -- SMALL_BIZ / GENERAL
    status                  VARCHAR(30) NOT NULL DEFAULT 'ONBOARDING',
                                                               -- ONBOARDING / READY_FOR_VOUCHERS / SUSPENDED
    activated_at            DATETIME    NULL,                  -- set when status → READY_FOR_VOUCHERS
    created_at              DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at              DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP
                                        ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (account_set_id),
    INDEX idx_as_tenant (tenant_id),
    CONSTRAINT fk_as_tenant FOREIGN KEY (tenant_id) REFERENCES tenant (tenant_id)
);

-- ------------------------------------------------------------
-- 3. User Account
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS user_account (
    user_id       BIGINT       NOT NULL AUTO_INCREMENT,
    tenant_id     BIGINT       NOT NULL,                       -- FK → tenant
    username      VARCHAR(50)  NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    display_name  VARCHAR(100) NOT NULL,
    role          VARCHAR(20)  NOT NULL DEFAULT 'ACCOUNTANT',
                                                               -- BOSS / ACCOUNTANT / DEPT_MANAGER
    department_id BIGINT       NULL,                           -- FK → department
    is_active     TINYINT(1)   NOT NULL DEFAULT 1,
    last_login_at DATETIME     NULL,
    created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
                               ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id),
    INDEX idx_ua_tenant (tenant_id),
    CONSTRAINT fk_ua_tenant FOREIGN KEY (tenant_id) REFERENCES tenant (tenant_id)
);

-- ------------------------------------------------------------
-- 4. Department — cost center
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS department (
    dept_id        BIGINT       NOT NULL AUTO_INCREMENT,
    tenant_id      BIGINT       NOT NULL,                      -- FK → tenant
    account_set_id BIGINT       NOT NULL,                      -- FK → account_set
    dept_name      VARCHAR(100) NOT NULL,
    cost_center    VARCHAR(50)  NULL,
    manager_id     BIGINT       NULL,                          -- FK → user_account.user_id
    is_active      TINYINT(1)   NOT NULL DEFAULT 1,
    created_at     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
                                ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (dept_id),
    INDEX idx_dept_tenant_as (tenant_id, account_set_id),
    CONSTRAINT fk_dept_tenant FOREIGN KEY (tenant_id)      REFERENCES tenant      (tenant_id),
    CONSTRAINT fk_dept_as     FOREIGN KEY (account_set_id) REFERENCES account_set (account_set_id)
);

-- ------------------------------------------------------------
-- 5. Auxiliary Entity — 辅助核算实体
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS auxiliary_entity (
    entity_id      BIGINT       NOT NULL AUTO_INCREMENT,
    tenant_id      BIGINT       NOT NULL,
    account_set_id BIGINT       NOT NULL,
    entity_type    VARCHAR(20)  NOT NULL,             -- 员工/部门/客户/供应商
    entity_name    VARCHAR(100) NOT NULL,
    is_active      TINYINT(1)   NOT NULL DEFAULT 1,
    created_at     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (entity_id),
    INDEX idx_ae_tenant_as (tenant_id, account_set_id),
    CONSTRAINT fk_ae_tenant FOREIGN KEY (tenant_id)      REFERENCES tenant      (tenant_id),
    CONSTRAINT fk_ae_as     FOREIGN KEY (account_set_id) REFERENCES account_set (account_set_id)
);

-- ------------------------------------------------------------
-- 6. Enterprise Profile — 企业税收画像
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS enterprise_profile (
    company_id                  BIGINT          NOT NULL AUTO_INCREMENT,
    tenant_id                   BIGINT          NOT NULL,
    account_set_id              BIGINT          NOT NULL,
    company_name                VARCHAR(200)    NOT NULL,
    company_type                VARCHAR(20)     NOT NULL DEFAULT 'MICRO',
    industry_code               VARCHAR(50)     NOT NULL DEFAULT '通用',
    tax_payer_type              VARCHAR(20)     NOT NULL DEFAULT 'SMALL_SCALE',
    applicable_income_tax_rate  DECIMAL(5, 4)   NOT NULL DEFAULT 0.2000,
    vat_rate                    DECIMAL(5, 4)   NOT NULL DEFAULT 0.0300,
    decision_threshold          DECIMAL(18, 2)  NOT NULL DEFAULT 5000.00,
    accounting_standard         VARCHAR(20)     NOT NULL DEFAULT 'SMALL_BIZ',
    province                    VARCHAR(50)     NULL,
    city                        VARCHAR(50)     NULL,
    is_hnte                     TINYINT(1)      NOT NULL DEFAULT 0,
    rd_eligible                 TINYINT(1)      NOT NULL DEFAULT 0,
    employee_count              INT             NULL,
    annual_revenue_estimate     DECIMAL(18, 2)  NULL,
    is_active                   TINYINT(1)      NOT NULL DEFAULT 1,
    created_at                  DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at                  DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP
                                                ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (company_id),
    INDEX idx_ep_tenant_as (tenant_id, account_set_id),
    CONSTRAINT fk_ep_tenant FOREIGN KEY (tenant_id)      REFERENCES tenant      (tenant_id),
    CONSTRAINT fk_ep_as     FOREIGN KEY (account_set_id) REFERENCES account_set (account_set_id)
);

-- ------------------------------------------------------------
-- 7. Operational Record — AI 缓冲池
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS operational_record (
    record_id      BIGINT       NOT NULL AUTO_INCREMENT,
    tenant_id      BIGINT       NOT NULL,
    account_set_id BIGINT       NOT NULL,
    raw_text       TEXT         NOT NULL,
    extracted_json TEXT         NULL,
    status         VARCHAR(30)  NOT NULL DEFAULT 'PENDING',
                                                    -- PENDING / PROCESSED / PENDING_BOSS_DECISION / MANUAL_REVIEW
    error_message  TEXT         NULL,
    created_at     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
                                ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (record_id),
    INDEX idx_or_tenant_as (tenant_id, account_set_id),
    INDEX idx_or_status    (tenant_id, account_set_id, status),
    CONSTRAINT fk_or_tenant FOREIGN KEY (tenant_id)      REFERENCES tenant      (tenant_id),
    CONSTRAINT fk_or_as     FOREIGN KEY (account_set_id) REFERENCES account_set (account_set_id)
);

-- ------------------------------------------------------------
-- 8. Voucher Header — 凭证主表
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS voucher_header (
    voucher_id     BIGINT         NOT NULL AUTO_INCREMENT,
    tenant_id      BIGINT         NOT NULL,
    account_set_id BIGINT         NOT NULL,
    record_id      BIGINT         NOT NULL,           -- FK → operational_record
    voucher_date   DATE           NOT NULL,
    total_amount   DECIMAL(18, 2) NOT NULL,
    memo           VARCHAR(500)   NULL,
    review_status  VARCHAR(20)    NOT NULL DEFAULT 'DRAFT',
                                                       -- DRAFT / PENDING_REVIEW / POSTED / REJECTED
    reviewer_id    BIGINT         NULL,
    review_note    VARCHAR(500)   NULL,
    reviewed_at    DATETIME       NULL,
    created_at     DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (voucher_id),
    INDEX idx_vh_tenant_as   (tenant_id, account_set_id),
    INDEX idx_vh_date        (tenant_id, account_set_id, voucher_date),
    INDEX idx_vh_status      (tenant_id, account_set_id, review_status),
    CONSTRAINT fk_vh_tenant FOREIGN KEY (tenant_id)      REFERENCES tenant             (tenant_id),
    CONSTRAINT fk_vh_as     FOREIGN KEY (account_set_id) REFERENCES account_set        (account_set_id),
    CONSTRAINT fk_vh_record FOREIGN KEY (record_id)      REFERENCES operational_record (record_id)
);

-- ------------------------------------------------------------
-- 9. Voucher Line — 凭证明细
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS voucher_line (
    line_id             BIGINT         NOT NULL AUTO_INCREMENT,
    tenant_id           BIGINT         NOT NULL,
    account_set_id      BIGINT         NOT NULL,
    voucher_id          BIGINT         NOT NULL,    -- FK → voucher_header
    subject_code        VARCHAR(10)    NOT NULL,    -- FK → account_subject
    direction           VARCHAR(10)    NOT NULL,    -- DEBIT / CREDIT
    amount              DECIMAL(18, 2) NOT NULL,
    auxiliary_entity_id BIGINT         NULL,        -- FK → auxiliary_entity
    memo                VARCHAR(200)   NULL,
    PRIMARY KEY (line_id),
    INDEX idx_vl_tenant_as    (tenant_id, account_set_id),
    INDEX idx_vl_subject      (tenant_id, account_set_id, subject_code),
    CONSTRAINT fk_vl_tenant  FOREIGN KEY (tenant_id)           REFERENCES tenant           (tenant_id),
    CONSTRAINT fk_vl_as      FOREIGN KEY (account_set_id)      REFERENCES account_set      (account_set_id),
    CONSTRAINT fk_vl_voucher FOREIGN KEY (voucher_id)           REFERENCES voucher_header   (voucher_id),
    CONSTRAINT fk_vl_subject FOREIGN KEY (subject_code)         REFERENCES account_subject  (subject_code),
    CONSTRAINT fk_vl_entity  FOREIGN KEY (auxiliary_entity_id) REFERENCES auxiliary_entity (entity_id),
    CONSTRAINT chk_vl_direction CHECK (direction IN ('DEBIT', 'CREDIT')),
    CONSTRAINT chk_vl_amount    CHECK (amount > 0)
);

-- ------------------------------------------------------------
-- 10. Boss Decision Log
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS boss_decision_log (
    decision_id        BIGINT       NOT NULL AUTO_INCREMENT,
    tenant_id          BIGINT       NOT NULL,
    account_set_id     BIGINT       NOT NULL,
    record_id          BIGINT       NOT NULL,           -- FK → operational_record
    ai_options_json    TEXT         NOT NULL,
    boss_choice        VARCHAR(50)  NULL,
    chosen_action_code VARCHAR(50)  NULL,
    status             VARCHAR(30)  NOT NULL DEFAULT 'PENDING_DECISION',
                                                         -- PENDING_DECISION / DECIDED / EXPIRED
    expires_at         DATETIME     NULL,
    decided_at         DATETIME     NULL,
    created_at         DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (decision_id),
    INDEX idx_bdl_tenant_as (tenant_id, account_set_id),
    INDEX idx_bdl_record    (tenant_id, account_set_id, record_id),
    CONSTRAINT fk_bdl_tenant FOREIGN KEY (tenant_id)      REFERENCES tenant             (tenant_id),
    CONSTRAINT fk_bdl_as     FOREIGN KEY (account_set_id) REFERENCES account_set        (account_set_id),
    CONSTRAINT fk_bdl_record FOREIGN KEY (record_id)      REFERENCES operational_record (record_id)
);

-- ------------------------------------------------------------
-- 11. Asset Register — 固定资产台账
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS asset_register (
    asset_id                    BIGINT          NOT NULL AUTO_INCREMENT,
    tenant_id                   BIGINT          NOT NULL,
    account_set_id              BIGINT          NOT NULL,
    voucher_id                  BIGINT          NOT NULL,
    decision_id                 BIGINT          NULL,
    asset_name                  VARCHAR(200)    NOT NULL,
    asset_category              VARCHAR(50)     NOT NULL DEFAULT '通用设备',
    original_value              DECIMAL(18, 2)  NOT NULL,
    net_salvage_value           DECIMAL(18, 2)  NOT NULL DEFAULT 0.00,
    depreciation_method         VARCHAR(20)     NOT NULL,
    useful_life_months          INT             NOT NULL,
    monthly_depreciation        DECIMAL(18, 2)  NOT NULL,
    accumulated_depreciation    DECIMAL(18, 2)  NOT NULL DEFAULT 0.00,
    depreciation_months_elapsed INT             NOT NULL DEFAULT 0,
    status                      VARCHAR(20)     NOT NULL DEFAULT 'IN_USE',
    purchase_date               DATE            NOT NULL,
    depreciation_start_month    VARCHAR(7)      NOT NULL,
    notes                       TEXT            NULL,
    created_at                  DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at                  DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP
                                                ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (asset_id),
    INDEX idx_ar_tenant_as (tenant_id, account_set_id),
    CONSTRAINT fk_ar_tenant   FOREIGN KEY (tenant_id)      REFERENCES tenant           (tenant_id),
    CONSTRAINT fk_ar_as       FOREIGN KEY (account_set_id) REFERENCES account_set      (account_set_id),
    CONSTRAINT fk_ar_voucher  FOREIGN KEY (voucher_id)     REFERENCES voucher_header   (voucher_id),
    CONSTRAINT fk_ar_decision FOREIGN KEY (decision_id)    REFERENCES boss_decision_log (decision_id)
);

-- ------------------------------------------------------------
-- 12. Accounting Period — 会计期间
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS accounting_period (
    period_id          BIGINT    NOT NULL AUTO_INCREMENT,
    tenant_id          BIGINT    NOT NULL,
    account_set_id     BIGINT    NOT NULL,
    year               INT       NOT NULL,
    month              INT       NOT NULL,             -- 1-12
    status             VARCHAR(10) NOT NULL DEFAULT 'OPEN',
                                                       -- OPEN / CLOSED
    closed_at          DATETIME  NULL,
    closed_by          BIGINT    NULL,                 -- FK → user_account
    closing_voucher_id BIGINT    NULL,                 -- FK → voucher_header
    created_at         DATETIME  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (period_id),
    UNIQUE KEY uq_period_ym (tenant_id, account_set_id, year, month),
    INDEX idx_ap_tenant_as (tenant_id, account_set_id),
    CONSTRAINT fk_ap_tenant FOREIGN KEY (tenant_id)      REFERENCES tenant      (tenant_id),
    CONSTRAINT fk_ap_as     FOREIGN KEY (account_set_id) REFERENCES account_set (account_set_id)
);

-- ------------------------------------------------------------
-- 13. Audit Log — 不可变操作轨迹
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_log (
    log_id        BIGINT       NOT NULL AUTO_INCREMENT,
    tenant_id     BIGINT       NOT NULL,              -- FK → tenant (cross-account-set)
    table_name    VARCHAR(50)  NOT NULL,
    record_id     VARCHAR(50)  NOT NULL,
    action        VARCHAR(20)  NOT NULL,               -- CREATE / UPDATE / DELETE / STATUS_CHANGE
    user_id       BIGINT       NULL,
    username      VARCHAR(50)  NULL,
    before_value  JSON         NULL,
    after_value   JSON         NULL,
    description   VARCHAR(500) NULL,
    ip_address    VARCHAR(45)  NULL,
    created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (log_id),
    INDEX idx_audit_tenant        (tenant_id),
    INDEX idx_audit_table_record  (table_name, record_id),
    INDEX idx_audit_created       (created_at),
    CONSTRAINT fk_audit_tenant FOREIGN KEY (tenant_id) REFERENCES tenant (tenant_id)
);

-- ------------------------------------------------------------
-- 14. Invoice — 发票台账
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS invoice (
    invoice_id        BIGINT        NOT NULL AUTO_INCREMENT,
    tenant_id         BIGINT        NOT NULL,
    account_set_id    BIGINT        NOT NULL,
    invoice_type      VARCHAR(20)   NOT NULL,          -- INPUT / OUTPUT
    invoice_code      VARCHAR(20)   NULL,
    invoice_number    VARCHAR(20)   NOT NULL,
    invoice_date      DATE          NOT NULL,
    seller_name       VARCHAR(200)  NULL,
    seller_tax_id     VARCHAR(20)   NULL,
    buyer_name        VARCHAR(200)  NULL,
    buyer_tax_id      VARCHAR(20)   NULL,
    subtotal_amount   DECIMAL(18,2) NOT NULL,
    tax_rate          DECIMAL(5,4)  NOT NULL DEFAULT 0.0,
    tax_amount        DECIMAL(18,2) NOT NULL,
    total_amount      DECIMAL(18,2) NOT NULL,
    items_summary     VARCHAR(500)  NULL,
    voucher_id        BIGINT        NULL,
    status            VARCHAR(20)   NOT NULL DEFAULT 'UNVERIFIED',
    source            VARCHAR(20)   NOT NULL DEFAULT 'MANUAL',
    image_path        VARCHAR(500)  NULL,
    created_by        BIGINT        NULL,
    created_at        DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at        DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP
                                    ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (invoice_id),
    UNIQUE KEY uq_invoice_number (tenant_id, account_set_id, invoice_code, invoice_number),
    INDEX idx_inv_tenant_as  (tenant_id, account_set_id),
    INDEX idx_inv_date       (invoice_date),
    CONSTRAINT fk_inv_tenant FOREIGN KEY (tenant_id)      REFERENCES tenant      (tenant_id),
    CONSTRAINT fk_inv_as     FOREIGN KEY (account_set_id) REFERENCES account_set (account_set_id)
);

-- ------------------------------------------------------------
-- 15. Expense Request — 费用申请审批
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS expense_request (
    request_id     BIGINT         NOT NULL AUTO_INCREMENT,
    tenant_id      BIGINT         NOT NULL,
    account_set_id BIGINT         NOT NULL,
    applicant_id   BIGINT         NOT NULL,           -- FK → user_account
    dept_id        BIGINT         NULL,               -- FK → department
    title          VARCHAR(200)   NOT NULL,
    amount         DECIMAL(18, 2) NOT NULL,
    expense_type   VARCHAR(100)   NOT NULL,
    description    TEXT           NULL,
    status         VARCHAR(20)    NOT NULL DEFAULT 'PENDING',
    reviewer_id    BIGINT         NULL,
    review_note    TEXT           NULL,
    reviewed_at    DATETIME       NULL,
    record_id      BIGINT         NULL,               -- FK → operational_record
    created_at     DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at     DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP
                                  ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (request_id),
    INDEX idx_er_tenant_as (tenant_id, account_set_id),
    CONSTRAINT fk_er_tenant FOREIGN KEY (tenant_id)      REFERENCES tenant      (tenant_id),
    CONSTRAINT fk_er_as     FOREIGN KEY (account_set_id) REFERENCES account_set (account_set_id)
);

-- ------------------------------------------------------------
-- 16. Tax Annual Plan — AI 年度节税路线图
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tax_annual_plan (
    plan_id        BIGINT      NOT NULL AUTO_INCREMENT,
    tenant_id      BIGINT      NOT NULL,
    account_set_id BIGINT      NOT NULL,
    company_id     BIGINT      NOT NULL,              -- FK → enterprise_profile
    year           INT         NOT NULL,
    plan_json      TEXT        NOT NULL,
    status         VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
                                                      -- ACTIVE / OUTDATED / DRAFT
    generated_at   DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at     DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP
                               ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (plan_id),
    INDEX idx_tap_tenant_as      (tenant_id, account_set_id),
    INDEX idx_tap_company_year   (company_id, year),
    CONSTRAINT fk_tap_tenant  FOREIGN KEY (tenant_id)      REFERENCES tenant             (tenant_id),
    CONSTRAINT fk_tap_as      FOREIGN KEY (account_set_id) REFERENCES account_set        (account_set_id),
    CONSTRAINT fk_tap_company FOREIGN KEY (company_id)     REFERENCES enterprise_profile (company_id)
);
