-- ============================================================
-- AgentLedger — 增量迁移脚本：V1.0 → V3.0
-- ============================================================
-- 使用方式：
--   mysql -u root -p agentledger < database/migrate_v1_to_v3.sql
--
-- 脚本使用 IF NOT EXISTS / ADD COLUMN IF NOT EXISTS 语法，
-- 可安全重复执行（幂等）。
-- MySQL 8.0+ 支持 ADD COLUMN IF NOT EXISTS。
-- ============================================================

SET NAMES utf8mb4;

-- ------------------------------------------------------------
-- Step 1: enterprise_profile — 新增 S3 RAG 精准过滤字段
-- ------------------------------------------------------------
ALTER TABLE enterprise_profile
    ADD COLUMN IF NOT EXISTS province               VARCHAR(50)    NULL DEFAULT NULL
        COMMENT '省份, e.g.广东省, 用于RAG省级政策过滤'
        AFTER accounting_standard,
    ADD COLUMN IF NOT EXISTS city                   VARCHAR(50)    NULL DEFAULT NULL
        COMMENT '城市, e.g.深圳市, 用于RAG城市政策过滤'
        AFTER province,
    ADD COLUMN IF NOT EXISTS is_hnte                TINYINT(1)     NOT NULL DEFAULT 0
        COMMENT '是否高新技术企业: 1=是(15%税率+100%研发加计)'
        AFTER city,
    ADD COLUMN IF NOT EXISTS rd_eligible            TINYINT(1)     NOT NULL DEFAULT 0
        COMMENT '是否具备研发加计扣除资格: 1=是'
        AFTER is_hnte,
    ADD COLUMN IF NOT EXISTS employee_count         INT            NULL DEFAULT NULL
        COMMENT '员工人数, 用于判断小微资格(≤300人)'
        AFTER rd_eligible,
    ADD COLUMN IF NOT EXISTS annual_revenue_estimate DECIMAL(18,2) NULL DEFAULT NULL
        COMMENT '上年度营收估算(元), 广告费限额基数/小微资格判断'
        AFTER employee_count;

-- ------------------------------------------------------------
-- Step 2: 新增表（如已存在则跳过）
-- ------------------------------------------------------------

-- 2a. boss_decision_log（V1可能没有）
CREATE TABLE IF NOT EXISTS boss_decision_log (
    decision_id         BIGINT       NOT NULL AUTO_INCREMENT,
    record_id           BIGINT       NOT NULL,
    ai_options_json     TEXT         NOT NULL,
    boss_choice         VARCHAR(50)  NULL,
    chosen_action_code  VARCHAR(50)  NULL,
    status              VARCHAR(30)  NOT NULL DEFAULT 'PENDING_DECISION',
    expires_at          DATETIME     NULL,
    decided_at          DATETIME     NULL,
    created_at          DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (decision_id),
    CONSTRAINT fk_bdl_record FOREIGN KEY (record_id)
        REFERENCES operational_record (record_id)
);

-- 2b. asset_register
CREATE TABLE IF NOT EXISTS asset_register (
    asset_id                    BIGINT          NOT NULL AUTO_INCREMENT,
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
    CONSTRAINT fk_ar_voucher  FOREIGN KEY (voucher_id)
        REFERENCES voucher_header (voucher_id),
    CONSTRAINT fk_ar_decision FOREIGN KEY (decision_id)
        REFERENCES boss_decision_log (decision_id)
);

-- 2c. department
CREATE TABLE IF NOT EXISTS department (
    dept_id     BIGINT       NOT NULL AUTO_INCREMENT,
    dept_name   VARCHAR(100) NOT NULL UNIQUE,
    cost_center VARCHAR(50)  NULL,
    manager_id  BIGINT       NULL,
    is_active   TINYINT(1)   NOT NULL DEFAULT 1,
    created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (dept_id)
);

-- 2d. expense_request
CREATE TABLE IF NOT EXISTS expense_request (
    request_id   BIGINT         NOT NULL AUTO_INCREMENT,
    applicant_id BIGINT         NOT NULL,
    dept_id      BIGINT         NULL,
    title        VARCHAR(200)   NOT NULL,
    amount       DECIMAL(18, 2) NOT NULL,
    expense_type VARCHAR(100)   NOT NULL,
    description  TEXT           NULL,
    status       VARCHAR(20)    NOT NULL DEFAULT 'PENDING',
    reviewer_id  BIGINT         NULL,
    review_note  TEXT           NULL,
    reviewed_at  DATETIME       NULL,
    record_id    BIGINT         NULL,
    created_at   DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at   DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (request_id)
);

-- 2e. user_account
CREATE TABLE IF NOT EXISTS user_account (
    user_id       BIGINT       NOT NULL AUTO_INCREMENT,
    username      VARCHAR(50)  NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    display_name  VARCHAR(100) NOT NULL,
    role          VARCHAR(20)  NOT NULL DEFAULT 'ACCOUNTANT',
    department_id BIGINT       NULL,
    is_active     TINYINT(1)   NOT NULL DEFAULT 1,
    last_login_at DATETIME     NULL,
    created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id)
);

-- 2f. accounting_period
CREATE TABLE IF NOT EXISTS accounting_period (
    period_id          BIGINT      NOT NULL AUTO_INCREMENT,
    year               INT         NOT NULL,
    month              INT         NOT NULL,
    status             VARCHAR(10) NOT NULL DEFAULT 'OPEN',
    closed_at          DATETIME    NULL,
    closed_by          BIGINT      NULL,
    closing_voucher_id BIGINT      NULL,
    created_at         DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (period_id),
    UNIQUE KEY uq_period_ym (year, month)
);

-- 2g. audit_log
CREATE TABLE IF NOT EXISTS audit_log (
    log_id        BIGINT       NOT NULL AUTO_INCREMENT,
    table_name    VARCHAR(50)  NOT NULL,
    record_id     VARCHAR(50)  NOT NULL,
    action        VARCHAR(20)  NOT NULL,
    user_id       BIGINT       NULL,
    username      VARCHAR(50)  NULL,
    before_value  JSON         NULL,
    after_value   JSON         NULL,
    description   VARCHAR(500) NULL,
    ip_address    VARCHAR(45)  NULL,
    created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (log_id),
    INDEX idx_audit_table_record (table_name, record_id),
    INDEX idx_audit_user (user_id),
    INDEX idx_audit_created (created_at)
);

-- 2h. invoice
CREATE TABLE IF NOT EXISTS invoice (
    invoice_id        BIGINT        NOT NULL AUTO_INCREMENT,
    invoice_type      VARCHAR(20)   NOT NULL,
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
    updated_at        DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (invoice_id),
    UNIQUE KEY uq_invoice_number (invoice_code, invoice_number),
    INDEX idx_invoice_date (invoice_date),
    INDEX idx_invoice_voucher (voucher_id),
    INDEX idx_invoice_type (invoice_type)
);

-- 2i. tax_annual_plan (S3新增)
CREATE TABLE IF NOT EXISTS tax_annual_plan (
    plan_id      BIGINT      NOT NULL AUTO_INCREMENT,
    company_id   BIGINT      NOT NULL,
    year         INT         NOT NULL,
    plan_json    TEXT        NOT NULL,
    status       VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
    generated_at DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at   DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (plan_id),
    INDEX idx_tap_company_year (company_id, year),
    CONSTRAINT fk_tap_company FOREIGN KEY (company_id)
        REFERENCES enterprise_profile (company_id)
);

-- ------------------------------------------------------------
-- Step 3: voucher_header — 补充 reviewer 相关字段（如旧版本缺少）
-- ------------------------------------------------------------
ALTER TABLE voucher_header
    ADD COLUMN IF NOT EXISTS reviewer_id  BIGINT       NULL AFTER review_status,
    ADD COLUMN IF NOT EXISTS review_note  VARCHAR(500) NULL AFTER reviewer_id,
    ADD COLUMN IF NOT EXISTS reviewed_at  DATETIME     NULL AFTER review_note;

-- ------------------------------------------------------------
-- Step 4: 默认用户（boss/accountant/manager，密码均为 123456）
-- ------------------------------------------------------------
INSERT INTO user_account (username, password_hash, display_name, role) VALUES
('boss',       '$2b$12$cSvJO7Ln37SMTY0p2x3LpOx7fcgczGq61tnlGwXdLv7K73CtBPk4O', '老板',    'BOSS'),
('accountant', '$2b$12$cSvJO7Ln37SMTY0p2x3LpOx7fcgczGq61tnlGwXdLv7K73CtBPk4O', '财务小王', 'ACCOUNTANT'),
('manager',    '$2b$12$cSvJO7Ln37SMTY0p2x3LpOx7fcgczGq61tnlGwXdLv7K73CtBPk4O', '部门主管', 'DEPT_MANAGER')
ON DUPLICATE KEY UPDATE display_name = VALUES(display_name);

-- ------------------------------------------------------------
-- 完成
-- ------------------------------------------------------------
SELECT '✅ Migration V1 → V3 completed successfully.' AS result;
