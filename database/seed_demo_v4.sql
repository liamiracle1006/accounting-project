-- ============================================================
-- AgentLedger V4.0 — 演示数据（星辰科技 2026年1-3月）
-- 执行前提：已运行 ddl.sql 和 seed_local.sql
-- ============================================================
USE agentledger;

-- 0. 期初建账
INSERT IGNORE INTO operational_record (record_id, tenant_id, account_set_id, raw_text, status, created_at) VALUES
(1001, 1, 1, '股东出资注册资本 500000 元，已存入公司银行账户', 'PROCESSED', '2025-12-31 10:00:00');

INSERT IGNORE INTO voucher_header (voucher_id, tenant_id, account_set_id, record_id, voucher_date, total_amount, memo, review_status) VALUES
(1001, 1, 1, 1001, '2025-12-31', 500000.00, '股东出资·注册资本', 'POSTED');

INSERT IGNORE INTO voucher_line (line_id, tenant_id, account_set_id, voucher_id, subject_code, direction, amount, memo) VALUES
(10001, 1, 1, 1001, '1002', 'DEBIT',  500000.00, '银行存款—注册资本到账'),
(10002, 1, 1, 1001, '3001', 'CREDIT', 500000.00, '实收资本');

-- 1月：项目回款
INSERT IGNORE INTO operational_record (record_id, tenant_id, account_set_id, raw_text, status, created_at) VALUES
(1101, 1, 1, '收到广州大华集团软件开发项目款 150000 元，工行转账到账', 'PROCESSED', '2026-01-06 09:30:00');

INSERT IGNORE INTO voucher_header (voucher_id, tenant_id, account_set_id, record_id, voucher_date, total_amount, memo, review_status) VALUES
(1101, 1, 1, 1101, '2026-01-06', 150000.00, '收广州大华集团项目款', 'POSTED');

INSERT IGNORE INTO voucher_line (line_id, tenant_id, account_set_id, voucher_id, subject_code, direction, amount, memo) VALUES
(11011, 1, 1, 1101, '1002', 'DEBIT',  150000.00, '银行存款'),
(11012, 1, 1, 1101, '6001', 'CREDIT', 150000.00, '主营业务收入—软件开发');

-- 1月：工资
INSERT IGNORE INTO operational_record (record_id, tenant_id, account_set_id, raw_text, status, created_at) VALUES
(1102, 1, 1, '发放1月员工工资共计 45000 元，银行代发', 'PROCESSED', '2026-01-20 10:00:00');

INSERT IGNORE INTO voucher_header (voucher_id, tenant_id, account_set_id, record_id, voucher_date, total_amount, memo, review_status) VALUES
(1102, 1, 1, 1102, '2026-01-20', 45000.00, '2026年1月工资', 'POSTED');

INSERT IGNORE INTO voucher_line (line_id, tenant_id, account_set_id, voucher_id, subject_code, direction, amount, memo) VALUES
(11021, 1, 1, 1102, '6602', 'DEBIT',  45000.00, '管理费用—工资'),
(11022, 1, 1, 1102, '1002', 'CREDIT', 45000.00, '银行存款');

-- 1月：租金
INSERT IGNORE INTO operational_record (record_id, tenant_id, account_set_id, raw_text, status, created_at) VALUES
(1103, 1, 1, '支付1月办公室租金 8000 元', 'PROCESSED', '2026-01-03 14:00:00');

INSERT IGNORE INTO voucher_header (voucher_id, tenant_id, account_set_id, record_id, voucher_date, total_amount, memo, review_status) VALUES
(1103, 1, 1, 1103, '2026-01-03', 8000.00, '1月办公室租金', 'POSTED');

INSERT IGNORE INTO voucher_line (line_id, tenant_id, account_set_id, voucher_id, subject_code, direction, amount, memo) VALUES
(11031, 1, 1, 1103, '6602', 'DEBIT',  8000.00, '管理费用—租金'),
(11032, 1, 1, 1103, '1002', 'CREDIT', 8000.00, '银行存款');

-- 1月：固定资产
INSERT IGNORE INTO operational_record (record_id, tenant_id, account_set_id, raw_text, status, created_at) VALUES
(1104, 1, 1, '采购联想笔记本电脑4台共计 18000 元，用于研发团队', 'PROCESSED', '2026-01-10 11:00:00');

INSERT IGNORE INTO voucher_header (voucher_id, tenant_id, account_set_id, record_id, voucher_date, total_amount, memo, review_status) VALUES
(1104, 1, 1, 1104, '2026-01-10', 18000.00, '采购研发用笔记本电脑', 'POSTED');

INSERT IGNORE INTO voucher_line (line_id, tenant_id, account_set_id, voucher_id, subject_code, direction, amount, memo) VALUES
(11041, 1, 1, 1104, '1601', 'DEBIT',  18000.00, '固定资产—电子设备'),
(11042, 1, 1, 1104, '1002', 'CREDIT', 18000.00, '银行存款');

-- 2月：项目款
INSERT IGNORE INTO operational_record (record_id, tenant_id, account_set_id, raw_text, status, created_at) VALUES
(1201, 1, 1, '收到深圳云信科技ERP定制项目首付款 180000 元', 'PROCESSED', '2026-02-07 10:00:00');

INSERT IGNORE INTO voucher_header (voucher_id, tenant_id, account_set_id, record_id, voucher_date, total_amount, memo, review_status) VALUES
(1201, 1, 1, 1201, '2026-02-07', 180000.00, '收深圳云信科技项目首付款', 'POSTED');

INSERT IGNORE INTO voucher_line (line_id, tenant_id, account_set_id, voucher_id, subject_code, direction, amount, memo) VALUES
(12011, 1, 1, 1201, '1002', 'DEBIT',  180000.00, '银行存款'),
(12012, 1, 1, 1201, '6001', 'CREDIT', 180000.00, '主营业务收入—软件定制');

-- 2月：工资
INSERT IGNORE INTO operational_record (record_id, tenant_id, account_set_id, raw_text, status, created_at) VALUES
(1202, 1, 1, '发放2月员工工资共计 45000 元', 'PROCESSED', '2026-02-20 10:00:00');

INSERT IGNORE INTO voucher_header (voucher_id, tenant_id, account_set_id, record_id, voucher_date, total_amount, memo, review_status) VALUES
(1202, 1, 1, 1202, '2026-02-20', 45000.00, '2026年2月工资', 'POSTED');

INSERT IGNORE INTO voucher_line (line_id, tenant_id, account_set_id, voucher_id, subject_code, direction, amount, memo) VALUES
(12021, 1, 1, 1202, '6602', 'DEBIT',  45000.00, '管理费用—工资'),
(12022, 1, 1, 1202, '1002', 'CREDIT', 45000.00, '银行存款');

-- 2月：租金
INSERT IGNORE INTO operational_record (record_id, tenant_id, account_set_id, raw_text, status, created_at) VALUES
(1203, 1, 1, '支付2月办公室租金 8000 元', 'PROCESSED', '2026-02-03 09:00:00');

INSERT IGNORE INTO voucher_header (voucher_id, tenant_id, account_set_id, record_id, voucher_date, total_amount, memo, review_status) VALUES
(1203, 1, 1, 1203, '2026-02-03', 8000.00, '2月办公室租金', 'POSTED');

INSERT IGNORE INTO voucher_line (line_id, tenant_id, account_set_id, voucher_id, subject_code, direction, amount, memo) VALUES
(12031, 1, 1, 1203, '6602', 'DEBIT',  8000.00, '管理费用—租金'),
(12032, 1, 1, 1203, '1002', 'CREDIT', 8000.00, '银行存款');

-- 2月：差旅
INSERT IGNORE INTO operational_record (record_id, tenant_id, account_set_id, raw_text, status, created_at) VALUES
(1204, 1, 1, '张三赴上海拜访客户差旅费报销 5200 元', 'PROCESSED', '2026-02-25 16:00:00');

INSERT IGNORE INTO voucher_header (voucher_id, tenant_id, account_set_id, record_id, voucher_date, total_amount, memo, review_status) VALUES
(1204, 1, 1, 1204, '2026-02-25', 5200.00, '销售差旅—张三上海出差', 'POSTED');

INSERT IGNORE INTO voucher_line (line_id, tenant_id, account_set_id, voucher_id, subject_code, direction, amount, memo) VALUES
(12041, 1, 1, 1204, '6601', 'DEBIT',  5200.00, '销售费用—差旅费'),
(12042, 1, 1, 1204, '1002', 'CREDIT', 5200.00, '银行存款');

-- 3月：项目款
INSERT IGNORE INTO operational_record (record_id, tenant_id, account_set_id, raw_text, status, created_at) VALUES
(1301, 1, 1, '收到北京智汇信息技术有限公司软件项目尾款 200000 元', 'PROCESSED', '2026-03-04 10:00:00');

INSERT IGNORE INTO voucher_header (voucher_id, tenant_id, account_set_id, record_id, voucher_date, total_amount, memo, review_status) VALUES
(1301, 1, 1, 1301, '2026-03-04', 200000.00, '收北京智汇信息项目尾款', 'POSTED');

INSERT IGNORE INTO voucher_line (line_id, tenant_id, account_set_id, voucher_id, subject_code, direction, amount, memo) VALUES
(13011, 1, 1, 1301, '1002', 'DEBIT',  200000.00, '银行存款'),
(13012, 1, 1, 1301, '6001', 'CREDIT', 200000.00, '主营业务收入');

-- 3月：应收账款
INSERT IGNORE INTO operational_record (record_id, tenant_id, account_set_id, raw_text, status, created_at) VALUES
(1302, 1, 1, '向杭州数联网络提供技术咨询服务，开票 30000 元', 'PROCESSED', '2026-03-20 14:00:00');

INSERT IGNORE INTO voucher_header (voucher_id, tenant_id, account_set_id, record_id, voucher_date, total_amount, memo, review_status) VALUES
(1302, 1, 1, 1302, '2026-03-20', 30000.00, '技术咨询服务收入', 'POSTED');

INSERT IGNORE INTO voucher_line (line_id, tenant_id, account_set_id, voucher_id, subject_code, direction, amount, memo) VALUES
(13021, 1, 1, 1302, '1122', 'DEBIT',  30000.00, '应收账款—杭州数联网络'),
(13022, 1, 1, 1302, '6001', 'CREDIT', 30000.00, '主营业务收入—咨询服务');

-- 3月：工资
INSERT IGNORE INTO operational_record (record_id, tenant_id, account_set_id, raw_text, status, created_at) VALUES
(1303, 1, 1, '发放3月员工工资及季度绩效共计 52000 元', 'PROCESSED', '2026-03-20 10:00:00');

INSERT IGNORE INTO voucher_header (voucher_id, tenant_id, account_set_id, record_id, voucher_date, total_amount, memo, review_status) VALUES
(1303, 1, 1, 1303, '2026-03-20', 52000.00, '2026年3月工资+绩效', 'POSTED');

INSERT IGNORE INTO voucher_line (line_id, tenant_id, account_set_id, voucher_id, subject_code, direction, amount, memo) VALUES
(13031, 1, 1, 1303, '6602', 'DEBIT',  52000.00, '管理费用—工资绩效'),
(13032, 1, 1, 1303, '1002', 'CREDIT', 52000.00, '银行存款');

-- 3月：租金
INSERT IGNORE INTO operational_record (record_id, tenant_id, account_set_id, raw_text, status, created_at) VALUES
(1304, 1, 1, '支付3月办公室租金 8000 元', 'PROCESSED', '2026-03-03 09:00:00');

INSERT IGNORE INTO voucher_header (voucher_id, tenant_id, account_set_id, record_id, voucher_date, total_amount, memo, review_status) VALUES
(1304, 1, 1, 1304, '2026-03-03', 8000.00, '3月办公室租金', 'POSTED');

INSERT IGNORE INTO voucher_line (line_id, tenant_id, account_set_id, voucher_id, subject_code, direction, amount, memo) VALUES
(13041, 1, 1, 1304, '6602', 'DEBIT',  8000.00, '管理费用—租金'),
(13042, 1, 1, 1304, '1002', 'CREDIT', 8000.00, '银行存款');

-- 3月：市场推广
INSERT IGNORE INTO operational_record (record_id, tenant_id, account_set_id, raw_text, status, created_at) VALUES
(1305, 1, 1, '支付软博会展位费及宣传材料制作费共计 15000 元', 'PROCESSED', '2026-03-10 11:00:00');

INSERT IGNORE INTO voucher_header (voucher_id, tenant_id, account_set_id, record_id, voucher_date, total_amount, memo, review_status) VALUES
(1305, 1, 1, 1305, '2026-03-10', 15000.00, '参加软博会市场推广', 'POSTED');

INSERT IGNORE INTO voucher_line (line_id, tenant_id, account_set_id, voucher_id, subject_code, direction, amount, memo) VALUES
(13051, 1, 1, 1305, '6601', 'DEBIT',  15000.00, '销售费用—展会推广'),
(13052, 1, 1, 1305, '1002', 'CREDIT', 15000.00, '银行存款');

-- 3月：研发外包
INSERT IGNORE INTO operational_record (record_id, tenant_id, account_set_id, raw_text, status, created_at) VALUES
(1306, 1, 1, '支付上海开源技术AI功能模块开发外包费用 22000 元', 'PROCESSED', '2026-03-15 15:00:00');

INSERT IGNORE INTO voucher_header (voucher_id, tenant_id, account_set_id, record_id, voucher_date, total_amount, memo, review_status) VALUES
(1306, 1, 1, 1306, '2026-03-15', 22000.00, 'AI模块研发外包', 'POSTED');

INSERT IGNORE INTO voucher_line (line_id, tenant_id, account_set_id, voucher_id, subject_code, direction, amount, memo) VALUES
(13061, 1, 1, 1306, '6604', 'DEBIT',  22000.00, '研发费用—外包开发'),
(13062, 1, 1, 1306, '1002', 'CREDIT', 22000.00, '银行存款');

SELECT '===== V4.0 演示数据导入完成 =====' AS info;
