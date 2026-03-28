-- ============================================================
-- AgentLedger — 演示数据（星辰科技有限公司 2026年1-3月）
-- 执行前提：已运行 ddl.sql 和 dml.sql
-- 可安全重复执行（INSERT IGNORE）
-- ============================================================
USE agentledger;

-- ============================================================
-- 0. 公司初始资本（期初建账）
-- ============================================================
INSERT IGNORE INTO operational_record (record_id, raw_text, status, created_at) VALUES
(1001, '股东出资注册资本 500000 元，已存入公司银行账户', 'PROCESSED', '2025-12-31 10:00:00');

INSERT IGNORE INTO voucher_header (voucher_id, record_id, voucher_date, total_amount, memo, review_status) VALUES
(1001, 1001, '2025-12-31', 500000.00, '股东出资·注册资本', 'POSTED');

INSERT IGNORE INTO voucher_line (line_id, voucher_id, subject_code, direction, amount, memo) VALUES
(10001, 1001, '1002', 'DEBIT',  500000.00, '银行存款—注册资本到账'),
(10002, 1001, '3001', 'CREDIT', 500000.00, '实收资本');

-- ============================================================
-- 1月份：软件项目回款 + 日常运营
-- ============================================================

-- 1-1. 收到广州大华集团项目款 ¥150,000
INSERT IGNORE INTO operational_record (record_id, raw_text, status, created_at) VALUES
(1101, '收到广州大华集团软件开发项目款 150000 元，工行转账到账', 'PROCESSED', '2026-01-06 09:30:00');

INSERT IGNORE INTO voucher_header (voucher_id, record_id, voucher_date, total_amount, memo, review_status) VALUES
(1101, 1101, '2026-01-06', 150000.00, '收广州大华集团项目款', 'POSTED');

INSERT IGNORE INTO voucher_line (line_id, voucher_id, subject_code, direction, amount, memo) VALUES
(11011, 1101, '1002', 'DEBIT',  150000.00, '银行存款'),
(11012, 1101, '6001', 'CREDIT', 150000.00, '主营业务收入—软件开发');

-- 1-2. 发放1月工资 ¥45,000
INSERT IGNORE INTO operational_record (record_id, raw_text, status, created_at) VALUES
(1102, '发放1月员工工资共计 45000 元，银行代发', 'PROCESSED', '2026-01-20 10:00:00');

INSERT IGNORE INTO voucher_header (voucher_id, record_id, voucher_date, total_amount, memo, review_status) VALUES
(1102, 1102, '2026-01-20', 45000.00, '2026年1月工资', 'POSTED');

INSERT IGNORE INTO voucher_line (line_id, voucher_id, subject_code, direction, amount, memo) VALUES
(11021, 1102, '6602', 'DEBIT',  45000.00, '管理费用—工资'),
(11022, 1102, '1002', 'CREDIT', 45000.00, '银行存款');

-- 1-3. 支付办公室租金 ¥8,000
INSERT IGNORE INTO operational_record (record_id, raw_text, status, created_at) VALUES
(1103, '支付1月办公室租金 8000 元，微信支付', 'PROCESSED', '2026-01-03 14:00:00');

INSERT IGNORE INTO voucher_header (voucher_id, record_id, voucher_date, total_amount, memo, review_status) VALUES
(1103, 1103, '2026-01-03', 8000.00, '1月办公室租金', 'POSTED');

INSERT IGNORE INTO voucher_line (line_id, voucher_id, subject_code, direction, amount, memo) VALUES
(11031, 1103, '6602', 'DEBIT',  8000.00, '管理费用—租金'),
(11032, 1103, '1002', 'CREDIT', 8000.00, '银行存款');

-- 1-4. 采购办公设备（笔记本电脑）¥18,000，固定资产
INSERT IGNORE INTO operational_record (record_id, raw_text, status, created_at) VALUES
(1104, '采购联想笔记本电脑4台共计 18000 元，用于研发团队', 'PROCESSED', '2026-01-10 11:00:00');

INSERT IGNORE INTO voucher_header (voucher_id, record_id, voucher_date, total_amount, memo, review_status) VALUES
(1104, 1104, '2026-01-10', 18000.00, '采购研发用笔记本电脑', 'POSTED');

INSERT IGNORE INTO voucher_line (line_id, voucher_id, subject_code, direction, amount, memo) VALUES
(11041, 1104, '1601', 'DEBIT',  18000.00, '固定资产—电子设备'),
(11042, 1104, '1002', 'CREDIT', 18000.00, '银行存款');

-- ============================================================
-- 2月份：新项目 + 差旅 + 日常运营
-- ============================================================

-- 2-1. 收到深圳云信科技项目款 ¥180,000
INSERT IGNORE INTO operational_record (record_id, raw_text, status, created_at) VALUES
(1201, '收到深圳云信科技ERP定制项目首付款 180000 元', 'PROCESSED', '2026-02-07 10:00:00');

INSERT IGNORE INTO voucher_header (voucher_id, record_id, voucher_date, total_amount, memo, review_status) VALUES
(1201, 1201, '2026-02-07', 180000.00, '收深圳云信科技项目首付款', 'POSTED');

INSERT IGNORE INTO voucher_line (line_id, voucher_id, subject_code, direction, amount, memo) VALUES
(12011, 1201, '1002', 'DEBIT',  180000.00, '银行存款'),
(12012, 1201, '6001', 'CREDIT', 180000.00, '主营业务收入—软件定制');

-- 2-2. 发放2月工资 ¥45,000
INSERT IGNORE INTO operational_record (record_id, raw_text, status, created_at) VALUES
(1202, '发放2月员工工资共计 45000 元', 'PROCESSED', '2026-02-20 10:00:00');

INSERT IGNORE INTO voucher_header (voucher_id, record_id, voucher_date, total_amount, memo, review_status) VALUES
(1202, 1202, '2026-02-20', 45000.00, '2026年2月工资', 'POSTED');

INSERT IGNORE INTO voucher_line (line_id, voucher_id, subject_code, direction, amount, memo) VALUES
(12021, 1202, '6602', 'DEBIT',  45000.00, '管理费用—工资'),
(12022, 1202, '1002', 'CREDIT', 45000.00, '银行存款');

-- 2-3. 支付2月租金 ¥8,000
INSERT IGNORE INTO operational_record (record_id, raw_text, status, created_at) VALUES
(1203, '支付2月办公室租金 8000 元', 'PROCESSED', '2026-02-03 09:00:00');

INSERT IGNORE INTO voucher_header (voucher_id, record_id, voucher_date, total_amount, memo, review_status) VALUES
(1203, 1203, '2026-02-03', 8000.00, '2月办公室租金', 'POSTED');

INSERT IGNORE INTO voucher_line (line_id, voucher_id, subject_code, direction, amount, memo) VALUES
(12031, 1203, '6602', 'DEBIT',  8000.00, '管理费用—租金'),
(12032, 1203, '1002', 'CREDIT', 8000.00, '银行存款');

-- 2-4. 销售出差差旅费 ¥5,200
INSERT IGNORE INTO operational_record (record_id, raw_text, status, created_at) VALUES
(1204, '张三赴上海拜访客户差旅费报销 5200 元，含机票酒店餐饮', 'PROCESSED', '2026-02-25 16:00:00');

INSERT IGNORE INTO voucher_header (voucher_id, record_id, voucher_date, total_amount, memo, review_status) VALUES
(1204, 1204, '2026-02-25', 5200.00, '销售差旅—张三上海出差', 'POSTED');

INSERT IGNORE INTO voucher_line (line_id, voucher_id, subject_code, direction, amount, memo) VALUES
(12041, 1204, '6601', 'DEBIT',  5200.00, '销售费用—差旅费'),
(12042, 1204, '1002', 'CREDIT', 5200.00, '银行存款');

-- ============================================================
-- 3月份：旺季冲刺（本月数据，当前仪表盘展示月份）
-- ============================================================

-- 3-1. 收到北京智汇信息项目款 ¥200,000
INSERT IGNORE INTO operational_record (record_id, raw_text, status, created_at) VALUES
(1301, '收到北京智汇信息技术有限公司软件项目尾款 200000 元', 'PROCESSED', '2026-03-04 10:00:00');

INSERT IGNORE INTO voucher_header (voucher_id, record_id, voucher_date, total_amount, memo, review_status) VALUES
(1301, 1301, '2026-03-04', 200000.00, '收北京智汇信息项目尾款', 'POSTED');

INSERT IGNORE INTO voucher_line (line_id, voucher_id, subject_code, direction, amount, memo) VALUES
(13011, 1301, '1002', 'DEBIT',  200000.00, '银行存款'),
(13012, 1301, '6001', 'CREDIT', 200000.00, '主营业务收入');

-- 3-2. 技术咨询服务收入 ¥30,000（应收账款，月末未到账）
INSERT IGNORE INTO operational_record (record_id, raw_text, status, created_at) VALUES
(1302, '向杭州数联网络提供技术咨询服务，开票 30000 元，月底到账', 'PROCESSED', '2026-03-20 14:00:00');

INSERT IGNORE INTO voucher_header (voucher_id, record_id, voucher_date, total_amount, memo, review_status) VALUES
(1302, 1302, '2026-03-20', 30000.00, '技术咨询服务收入', 'POSTED');

INSERT IGNORE INTO voucher_line (line_id, voucher_id, subject_code, direction, amount, memo) VALUES
(13021, 1302, '1122', 'DEBIT',  30000.00, '应收账款—杭州数联网络'),
(13022, 1302, '6001', 'CREDIT', 30000.00, '主营业务收入—咨询服务');

-- 3-3. 发放3月工资（含绩效提升）¥52,000
INSERT IGNORE INTO operational_record (record_id, raw_text, status, created_at) VALUES
(1303, '发放3月员工工资及季度绩效共计 52000 元', 'PROCESSED', '2026-03-20 10:00:00');

INSERT IGNORE INTO voucher_header (voucher_id, record_id, voucher_date, total_amount, memo, review_status) VALUES
(1303, 1303, '2026-03-20', 52000.00, '2026年3月工资+绩效', 'POSTED');

INSERT IGNORE INTO voucher_line (line_id, voucher_id, subject_code, direction, amount, memo) VALUES
(13031, 1303, '6602', 'DEBIT',  52000.00, '管理费用—工资绩效'),
(13032, 1303, '1002', 'CREDIT', 52000.00, '银行存款');

-- 3-4. 支付3月租金 ¥8,000
INSERT IGNORE INTO operational_record (record_id, raw_text, status, created_at) VALUES
(1304, '支付3月办公室租金 8000 元', 'PROCESSED', '2026-03-03 09:00:00');

INSERT IGNORE INTO voucher_header (voucher_id, record_id, voucher_date, total_amount, memo, review_status) VALUES
(1304, 1304, '2026-03-03', 8000.00, '3月办公室租金', 'POSTED');

INSERT IGNORE INTO voucher_line (line_id, voucher_id, subject_code, direction, amount, memo) VALUES
(13041, 1304, '6602', 'DEBIT',  8000.00, '管理费用—租金'),
(13042, 1304, '1002', 'CREDIT', 8000.00, '银行存款');

-- 3-5. 市场推广费用 ¥15,000（参加软博会展览）
INSERT IGNORE INTO operational_record (record_id, raw_text, status, created_at) VALUES
(1305, '支付第十届中国软件博览会展位费及宣传材料制作费共计 15000 元', 'PROCESSED', '2026-03-10 11:00:00');

INSERT IGNORE INTO voucher_header (voucher_id, record_id, voucher_date, total_amount, memo, review_status) VALUES
(1305, 1305, '2026-03-10', 15000.00, '参加软博会市场推广', 'POSTED');

INSERT IGNORE INTO voucher_line (line_id, voucher_id, subject_code, direction, amount, memo) VALUES
(13051, 1305, '6601', 'DEBIT',  15000.00, '销售费用—展会推广'),
(13052, 1305, '1002', 'CREDIT', 15000.00, '银行存款');

-- 3-6. 研发投入：AI模块开发外包 ¥22,000
INSERT IGNORE INTO operational_record (record_id, raw_text, status, created_at) VALUES
(1306, '支付上海开源技术AI功能模块开发外包费用 22000 元', 'PROCESSED', '2026-03-15 15:00:00');

INSERT IGNORE INTO voucher_header (voucher_id, record_id, voucher_date, total_amount, memo, review_status) VALUES
(1306, 1306, '2026-03-15', 22000.00, 'AI模块研发外包', 'POSTED');

INSERT IGNORE INTO voucher_line (line_id, voucher_id, subject_code, direction, amount, memo) VALUES
(13061, 1306, '6604', 'DEBIT',  22000.00, '研发费用—外包开发'),
(13062, 1306, '1002', 'CREDIT', 22000.00, '银行存款');

-- ============================================================
-- 固定资产台账（asset_register）
-- ============================================================

-- 笔记本电脑4台，2026-01购入，直线法36个月折旧
-- 月折旧额 = 18000 / 36 = 500 元
-- 截至2026-03已计提2个月（2月+3月）= 1000 元
INSERT IGNORE INTO asset_register (
    asset_id, voucher_id, decision_id,
    asset_name, asset_category,
    original_value, net_salvage_value,
    depreciation_method, useful_life_months, monthly_depreciation,
    accumulated_depreciation, depreciation_months_elapsed,
    status, purchase_date, depreciation_start_month, notes
) VALUES (
    1001, 1104, NULL,
    '联想笔记本电脑（4台）', '电子设备',
    18000.00, 0.00,
    'STRAIGHT_LINE', 36, 500.00,
    1000.00, 2,
    'IN_USE', '2026-01-10', '2026-02', '研发团队用机，资产编号 PC-2026-001至004'
);

-- 对应折旧凭证：2月计提折旧 ¥500
INSERT IGNORE INTO operational_record (record_id, raw_text, status, created_at) VALUES
(1401, '2026年2月计提固定资产折旧—笔记本电脑 500 元', 'PROCESSED', '2026-02-28 23:00:00');

INSERT IGNORE INTO voucher_header (voucher_id, record_id, voucher_date, total_amount, memo, review_status) VALUES
(1401, 1401, '2026-02-28', 500.00, '2月固定资产折旧', 'POSTED');

INSERT IGNORE INTO voucher_line (line_id, voucher_id, subject_code, direction, amount, memo) VALUES
(14011, 1401, '6602', 'DEBIT',  500.00, '管理费用—折旧费'),
(14012, 1401, '1602', 'CREDIT', 500.00, '累计折旧—电子设备');

-- 对应折旧凭证：3月计提折旧 ¥500
INSERT IGNORE INTO operational_record (record_id, raw_text, status, created_at) VALUES
(1402, '2026年3月计提固定资产折旧—笔记本电脑 500 元', 'PROCESSED', '2026-03-31 23:00:00');

INSERT IGNORE INTO voucher_header (voucher_id, record_id, voucher_date, total_amount, memo, review_status) VALUES
(1402, 1402, '2026-03-31', 500.00, '3月固定资产折旧', 'POSTED');

INSERT IGNORE INTO voucher_line (line_id, voucher_id, subject_code, direction, amount, memo) VALUES
(14021, 1402, '6602', 'DEBIT',  500.00, '管理费用—折旧费'),
(14022, 1402, '1602', 'CREDIT', 500.00, '累计折旧—电子设备');

-- ============================================================
-- 验证查询
-- ============================================================
SELECT '===== 演示数据导入完成 =====' AS info;

SELECT
    MONTH(h.voucher_date) AS 月份,
    COUNT(DISTINCT h.voucher_id) AS 凭证数,
    SUM(CASE WHEN l.subject_code BETWEEN '6001' AND '6399' AND l.direction='CREDIT' THEN l.amount ELSE 0 END) AS 收入,
    SUM(CASE WHEN l.subject_code BETWEEN '6400' AND '6899' AND l.direction='DEBIT'  THEN l.amount ELSE 0 END) AS 费用
FROM voucher_header h
JOIN voucher_line l ON l.voucher_id = h.voucher_id
WHERE h.review_status = 'POSTED'
  AND YEAR(h.voucher_date) = 2026
GROUP BY MONTH(h.voucher_date)
ORDER BY 月份;
