"""
Unit tests for ai/json_parser.py
Tests the JSON parsing layer in isolation — no DB, no LLM required.
"""
import pytest
from decimal import Decimal
from ai.json_parser import parse_llm_output, JSONParseError, ExtractedRecord


class TestParseValidInput:
    def test_basic_expense(self):
        raw = '{"amount":800,"currency":"CNY","expense_type":"招待费","payment_method":"员工垫付","payer_name":"张三","counterparty":null,"memo":"招待客户餐费","confidence":0.95}'
        rec = parse_llm_output(raw)
        assert isinstance(rec, ExtractedRecord)
        assert rec.amount == Decimal("800")
        assert rec.expense_type == "招待费"
        assert rec.payment_method == "员工垫付"
        assert rec.payer_name == "张三"
        assert rec.counterparty is None
        assert rec.confidence == pytest.approx(0.95)

    def test_decimal_amount(self):
        raw = '{"amount":245.5,"expense_type":"办公用品","payment_method":"微信支付","memo":"测试","confidence":0.98}'
        rec = parse_llm_output(raw)
        assert rec.amount == Decimal("245.5")

    def test_strips_markdown_fence(self):
        raw = '```json\n{"amount":100,"expense_type":"差旅费","payment_method":"银行转账","memo":"出差","confidence":0.9}\n```'
        rec = parse_llm_output(raw)
        assert rec.amount == Decimal("100")

    def test_unknown_payment_method_defaults_to_unspecified(self):
        raw = '{"amount":500,"expense_type":"广告费","payment_method":"某未知方式","memo":"广告","confidence":0.7}'
        rec = parse_llm_output(raw)
        assert rec.payment_method == "未指定"

    def test_income_type(self):
        raw = '{"amount":50000,"expense_type":"销售收款","payment_method":"银行转账","counterparty":"A公司","memo":"收款","confidence":0.96}'
        rec = parse_llm_output(raw)
        assert rec.amount == Decimal("50000")
        assert rec.counterparty == "A公司"


class TestParseInvalidInput:
    def test_missing_amount_raises(self):
        raw = '{"expense_type":"招待费","payment_method":"现金","memo":"x","confidence":0.9}'
        with pytest.raises(JSONParseError, match="amount"):
            parse_llm_output(raw)

    def test_zero_amount_raises(self):
        raw = '{"amount":0,"expense_type":"招待费","payment_method":"现金","memo":"x","confidence":0.9}'
        with pytest.raises(JSONParseError, match="positive"):
            parse_llm_output(raw)

    def test_negative_amount_raises(self):
        raw = '{"amount":-100,"expense_type":"招待费","payment_method":"现金","memo":"x","confidence":0.9}'
        with pytest.raises(JSONParseError, match="positive"):
            parse_llm_output(raw)

    def test_malformed_json_raises(self):
        with pytest.raises(JSONParseError, match="invalid JSON"):
            parse_llm_output("这不是JSON {broken")

    def test_empty_expense_type_raises(self):
        raw = '{"amount":100,"expense_type":"","payment_method":"现金","memo":"x","confidence":0.9}'
        with pytest.raises(JSONParseError, match="expense_type"):
            parse_llm_output(raw)

    def test_non_object_root_raises(self):
        with pytest.raises(JSONParseError, match="object"):
            parse_llm_output('[1, 2, 3]')

    def test_string_amount_still_works(self):
        # LLM might sometimes wrap amount in quotes; we coerce to Decimal
        raw = '{"amount":"300","expense_type":"办公用品","payment_method":"现金","memo":"x","confidence":0.8}'
        rec = parse_llm_output(raw)
        assert rec.amount == Decimal("300")
