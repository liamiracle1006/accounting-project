"""
Unit tests for services/accounting_engine.py
Uses an in-memory SQLite DB so no MySQL required.
"""
import pytest
from decimal import Decimal
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.connection import Base
from models.account_subject import AccountSubject
from models.auxiliary_entity import AuxiliaryEntity
from models.operational_record import OperationalRecord, RecordStatus
from models.voucher_header import VoucherHeader
from models.voucher_line import VoucherLine
from ai.json_parser import ExtractedRecord
from services.accounting_engine import AccountingEngineService, AccountingError


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def engine():
    eng = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(bind=eng)
    return eng


@pytest.fixture
def db(engine):
    """Fresh session per test with rollback isolation."""
    connection  = engine.connect()
    transaction = connection.begin()
    Session     = sessionmaker(bind=connection)
    session     = Session()

    # Seed master data
    subjects = [
        AccountSubject(subject_code="1001", subject_name="库存现金",     subject_type="资产", direction="DEBIT"),
        AccountSubject(subject_code="1002", subject_name="银行存款",     subject_type="资产", direction="DEBIT"),
        AccountSubject(subject_code="1012", subject_name="其他货币资金", subject_type="资产", direction="DEBIT"),
        AccountSubject(subject_code="1403", subject_name="原材料",       subject_type="资产", direction="DEBIT"),
        AccountSubject(subject_code="2241", subject_name="其他应付款",   subject_type="负债", direction="CREDIT"),
        AccountSubject(subject_code="6001", subject_name="主营业务收入", subject_type="收入", direction="CREDIT"),
        AccountSubject(subject_code="6601", subject_name="销售费用",     subject_type="费用", direction="DEBIT"),
        AccountSubject(subject_code="6602", subject_name="管理费用",     subject_type="费用", direction="DEBIT"),
    ]
    session.bulk_save_objects(subjects)

    entities = [
        AuxiliaryEntity(entity_type="员工", entity_name="张三"),
        AuxiliaryEntity(entity_type="客户", entity_name="A公司"),
    ]
    session.bulk_save_objects(entities)
    session.flush()

    yield session

    session.close()
    transaction.rollback()
    connection.close()


def _make_record(db) -> OperationalRecord:
    r = OperationalRecord(raw_text="test", status=RecordStatus.PENDING)
    db.add(r)
    db.flush()
    return r


def _make_extracted(**kwargs) -> ExtractedRecord:
    defaults = dict(
        amount=Decimal("800"),
        currency="CNY",
        expense_type="招待费",
        payment_method="员工垫付",
        payer_name="张三",
        counterparty=None,
        memo="招待客户",
        confidence=0.95,
        raw_json="{}",
    )
    defaults.update(kwargs)
    return ExtractedRecord(**defaults)


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestExpenseVoucher:
    def test_balanced_entry_created(self, db):
        record   = _make_record(db)
        ext      = _make_extracted()
        engine   = AccountingEngineService(db)
        voucher  = engine.generate_voucher(record, ext)

        assert voucher.voucher_id is not None
        assert voucher.total_amount == Decimal("800")

        lines = db.query(VoucherLine).filter_by(voucher_id=voucher.voucher_id).all()
        assert len(lines) == 2

        debits  = [l for l in lines if l.direction == "DEBIT"]
        credits = [l for l in lines if l.direction == "CREDIT"]
        assert sum(l.amount for l in debits)  == sum(l.amount for l in credits)

    def test_entertainment_maps_to_6601(self, db):
        record  = _make_record(db)
        ext     = _make_extracted(expense_type="招待费", payment_method="现金")
        engine  = AccountingEngineService(db)
        voucher = engine.generate_voucher(record, ext)
        lines   = db.query(VoucherLine).filter_by(voucher_id=voucher.voucher_id).all()
        debit_codes = {l.subject_code for l in lines if l.direction == "DEBIT"}
        assert "6601" in debit_codes

    def test_travel_maps_to_6602(self, db):
        record  = _make_record(db)
        ext     = _make_extracted(expense_type="差旅费", payment_method="银行转账")
        engine  = AccountingEngineService(db)
        voucher = engine.generate_voucher(record, ext)
        lines   = db.query(VoucherLine).filter_by(voucher_id=voucher.voucher_id).all()
        debit_codes = {l.subject_code for l in lines if l.direction == "DEBIT"}
        assert "6602" in debit_codes

    def test_employee_advance_credit_2241(self, db):
        record  = _make_record(db)
        ext     = _make_extracted(payment_method="员工垫付")
        engine  = AccountingEngineService(db)
        voucher = engine.generate_voucher(record, ext)
        lines   = db.query(VoucherLine).filter_by(voucher_id=voucher.voucher_id).all()
        credit_codes = {l.subject_code for l in lines if l.direction == "CREDIT"}
        assert "2241" in credit_codes

    def test_wechat_pay_credit_1012(self, db):
        record  = _make_record(db)
        ext     = _make_extracted(payment_method="微信支付")
        engine  = AccountingEngineService(db)
        voucher = engine.generate_voucher(record, ext)
        lines   = db.query(VoucherLine).filter_by(voucher_id=voucher.voucher_id).all()
        credit_codes = {l.subject_code for l in lines if l.direction == "CREDIT"}
        assert "1012" in credit_codes


class TestIncomeVoucher:
    def test_income_debit_1002_credit_6001(self, db):
        record  = _make_record(db)
        ext     = _make_extracted(
            amount=Decimal("50000"), expense_type="销售收款",
            payment_method="银行转账", payer_name=None, counterparty="A公司"
        )
        engine  = AccountingEngineService(db)
        voucher = engine.generate_voucher(record, ext)
        lines   = db.query(VoucherLine).filter_by(voucher_id=voucher.voucher_id).all()

        debit_codes  = {l.subject_code for l in lines if l.direction == "DEBIT"}
        credit_codes = {l.subject_code for l in lines if l.direction == "CREDIT"}
        assert "1002" in debit_codes
        assert "6001" in credit_codes

    def test_income_balanced(self, db):
        record  = _make_record(db)
        ext     = _make_extracted(amount=Decimal("12345.67"), expense_type="回款")
        engine  = AccountingEngineService(db)
        voucher = engine.generate_voucher(record, ext)
        lines   = db.query(VoucherLine).filter_by(voucher_id=voucher.voucher_id).all()
        total_d = sum(l.amount for l in lines if l.direction == "DEBIT")
        total_c = sum(l.amount for l in lines if l.direction == "CREDIT")
        assert total_d == total_c


class TestAutoCreateEntity:
    def test_unknown_entity_auto_created(self, db):
        record  = _make_record(db)
        ext     = _make_extracted(payer_name="未知员工王五")
        engine  = AccountingEngineService(db)
        engine.generate_voucher(record, ext)

        new_entity = (
            db.query(AuxiliaryEntity)
            .filter_by(entity_name="未知员工王五")
            .first()
        )
        assert new_entity is not None
        assert new_entity.entity_type == "未分类"
