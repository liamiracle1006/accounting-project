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
