-- ============================================================
-- AgentLedger V4.0 — 本地开发种子数据
-- ============================================================

-- 1. 科目表（无租户，全局共享）
INSERT INTO account_subject (subject_code, subject_name, subject_type, direction) VALUES
('1001', '库存现金',         '资产', 'DEBIT'),
('1002', '银行存款',         '资产', 'DEBIT'),
('1012', '其他货币资金',     '资产', 'DEBIT'),
('1101', '交易性金融资产',   '资产', 'DEBIT'),
('1111', '应收票据',         '资产', 'DEBIT'),
('1121', '应收股利',         '资产', 'DEBIT'),
('1122', '应收账款',         '资产', 'DEBIT'),
('1123', '预付账款',         '资产', 'DEBIT'),
('1221', '其他应收款',       '资产', 'DEBIT'),
('1231', '长期应收款',       '资产', 'DEBIT'),
('1401', '材料采购',         '资产', 'DEBIT'),
('1403', '原材料',           '资产', 'DEBIT'),
('1405', '库存商品',         '资产', 'DEBIT'),
('1501', '长期股权投资',     '资产', 'DEBIT'),
('1601', '固定资产',         '资产', 'DEBIT'),
('1602', '累计折旧',         '资产', 'CREDIT'),
('1604', '在建工程',         '资产', 'DEBIT'),
('1701', '无形资产',         '资产', 'DEBIT'),
('1702', '开发支出',         '资产', 'DEBIT'),
('1801', '长期待摊费用',     '资产', 'DEBIT'),
('1811', '递延所得税资产',   '资产', 'DEBIT'),
('1131', '坏账准备',         '资产', 'CREDIT'),
('1603', '固定资产清理',     '资产', 'DEBIT'),
('1703', '累计摊销',         '资产', 'CREDIT'),
('2001', '短期借款',         '负债', 'CREDIT'),
('2201', '应付票据',         '负债', 'CREDIT'),
('2202', '应付账款',         '负债', 'CREDIT'),
('2203', '预收款项',         '负债', 'CREDIT'),
('2211', '应付职工薪酬',     '负债', 'CREDIT'),
('2221', '应交税费',         '负债', 'CREDIT'),
('2231', '应付利息',         '负债', 'CREDIT'),
('2241', '其他应付款',       '负债', 'CREDIT'),
('2205', '合同负债',         '负债', 'CREDIT'),
('2401', '递延收益',         '负债', 'CREDIT'),
('2441', '递延所得税负债',   '负债', 'CREDIT'),
('2501', '长期借款',         '负债', 'CREDIT'),
('2601', '预计负债',         '负债', 'CREDIT'),
('4001', '实收资本',         '权益', 'CREDIT'),
('4002', '资本公积',         '权益', 'CREDIT'),
('4101', '盈余公积',         '权益', 'CREDIT'),
('4103', '本年利润',         '权益', 'CREDIT'),
('4104', '利润分配',         '权益', 'CREDIT'),
('4005', '其他综合收益',     '权益', 'CREDIT'),
('6401', '主营业务成本',     '费用', 'DEBIT'),
('6402', '其他业务成本',     '费用', 'DEBIT'),
('6403', '税金及附加',       '费用', 'DEBIT'),
('6601', '销售费用',         '费用', 'DEBIT'),
('6602', '管理费用',         '费用', 'DEBIT'),
('6603', '财务费用',         '费用', 'DEBIT'),
('6604', '研发费用',         '费用', 'DEBIT'),
('6701', '资产减值损失',     '费用', 'DEBIT'),
('6711', '营业外支出',       '费用', 'DEBIT'),
('6801', '所得税费用',       '费用', 'DEBIT'),
('6120', '信用减值损失',     '费用', 'DEBIT'),
('6001', '主营业务收入',     '收入', 'CREDIT'),
('6051', '其他业务收入',     '收入', 'CREDIT'),
('6101', '公允价值变动收益', '收入', 'CREDIT'),
('6111', '投资收益',         '收入', 'CREDIT'),
('6117', '其他收益',         '收入', 'CREDIT'),
('6301', '营业外收入',       '收入', 'CREDIT'),
('6115', '资产处置收益',     '收入', 'CREDIT')
ON DUPLICATE KEY UPDATE subject_name = VALUES(subject_name);

-- 2. 租户
INSERT INTO tenant (tenant_id, tenant_name, contact_email, status) VALUES
(1, '星辰科技有限公司', 'admin@example.com', 'ACTIVE')
ON DUPLICATE KEY UPDATE tenant_name = VALUES(tenant_name);

-- 3. 账套
INSERT INTO account_set (account_set_id, tenant_id, account_set_name, accounting_standard, status) VALUES
(1, 1, '默认账套', 'SMALL_BIZ', 'READY_FOR_VOUCHERS')
ON DUPLICATE KEY UPDATE account_set_name = VALUES(account_set_name);

-- 4. 用户（密码均为 123456）
INSERT INTO user_account (tenant_id, username, password_hash, display_name, role) VALUES
(1, 'boss',       '$2b$12$cSvJO7Ln37SMTY0p2x3LpOx7fcgczGq61tnlGwXdLv7K73CtBPk4O', '老板',    'BOSS'),
(1, 'accountant', '$2b$12$cSvJO7Ln37SMTY0p2x3LpOx7fcgczGq61tnlGwXdLv7K73CtBPk4O', '财务小王', 'ACCOUNTANT'),
(1, 'manager',    '$2b$12$cSvJO7Ln37SMTY0p2x3LpOx7fcgczGq61tnlGwXdLv7K73CtBPk4O', '部门主管', 'DEPT_MANAGER')
ON DUPLICATE KEY UPDATE display_name = VALUES(display_name);
