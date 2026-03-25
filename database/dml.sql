-- ============================================================
-- AgentLedger V2.0 — DML 初始化种子数据
-- ============================================================

-- ------------------------------------------------------------
-- 企业档案默认数据（示例：小微企业）
-- 生产环境请通过 POST /api/enterprise/profile 接口创建真实数据
-- ------------------------------------------------------------
INSERT INTO enterprise_profile (
    company_name, company_type, industry_code,
    tax_payer_type, applicable_income_tax_rate,
    vat_rate, decision_threshold, accounting_standard, is_active
) VALUES (
    '示例企业（请修改）', 'MICRO', '通用',
    'SMALL_SCALE', 0.2000,
    0.0300, 5000.00, 'SMALL_BIZ', 1
) ON DUPLICATE KEY UPDATE company_name = VALUES(company_name);

-- ------------------------------------------------------------
-- 会计科目 (Account Subject) 初始数据
-- direction: 资产/费用 借方增加(DEBIT)；负债/权益/收入 贷方增加(CREDIT)
-- ------------------------------------------------------------
INSERT INTO account_subject (subject_code, subject_name, subject_type, direction) VALUES
-- 资产类
('1001', '库存现金',       '资产', 'DEBIT'),
('1002', '银行存款',       '资产', 'DEBIT'),
('1012', '其他货币资金',   '资产', 'DEBIT'),
('1122', '应收账款',       '资产', 'DEBIT'),
('1221', '其他应收款',     '资产', 'DEBIT'),   -- 员工垫付款挂账
('1403', '原材料',         '资产', 'DEBIT'),
-- 负债类
('2202', '应付账款',       '负债', 'CREDIT'),
('2211', '应付职工薪酬',   '负债', 'CREDIT'),
('2241', '其他应付款',     '负债', 'CREDIT'),  -- 员工报销待付
-- 费用类
('6601', '销售费用',       '费用', 'DEBIT'),
('6602', '管理费用',       '费用', 'DEBIT'),
('6603', '财务费用',       '费用', 'DEBIT'),
-- 收入类
('6001', '主营业务收入',   '收入', 'CREDIT'),
('6051', '其他业务收入',   '收入', 'CREDIT')
ON DUPLICATE KEY UPDATE subject_name = VALUES(subject_name);

-- ------------------------------------------------------------
-- 辅助核算实体 (Auxiliary Entity) 初始数据
-- ------------------------------------------------------------
INSERT INTO auxiliary_entity (entity_type, entity_name) VALUES
('员工', '张三'),
('员工', '李四'),
('部门', '销售部'),
('部门', '行政部'),
('客户', '测试客户A'),
('供应商', '测试供应商B');

-- ------------------------------------------------------------
-- 验证查询（可选执行）
-- ------------------------------------------------------------
-- SELECT * FROM account_subject;
-- SELECT * FROM auxiliary_entity;
