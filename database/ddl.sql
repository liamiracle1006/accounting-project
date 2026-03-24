-- ============================================================
-- AgentLedger V1.0 — DDL
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
-- 3. 业务流水表 (Operational Record) — AI 缓冲池
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS operational_record (
    record_id      BIGINT       NOT NULL AUTO_INCREMENT,
    raw_text       TEXT         NOT NULL,           -- 原始自然语言输入
    extracted_json TEXT         NULL,               -- LLM 返回的 JSON
    status         VARCHAR(30)  NOT NULL DEFAULT 'PENDING',
                                                    -- PENDING / PROCESSED / MANUAL_REVIEW
    error_message  TEXT         NULL,               -- 失败原因
    created_at     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
                                ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (record_id)
);

-- ------------------------------------------------------------
-- 4. 凭证主表 (Voucher Header)
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
-- 5. 凭证明细表 (Voucher Line)
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
