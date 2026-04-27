"""
Integration tests for FastAPI routes using TestClient.
The LLM call is mocked so no real API key is needed.
"""
import json
import pytest
from decimal import Decimal
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.connection import Base, get_db
from models.account_subject import AccountSubject
from models.auxiliary_entity import AuxiliaryEntity
from main import app


# ── In-memory DB setup ────────────────────────────────────────────────────────

TEST_DB_URL = "sqlite:///:memory:"

@pytest.fixture(scope="module")
def test_engine():
    eng = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    return eng


@pytest.fixture(scope="module")
def seeded_session_factory(test_engine):
    SessionLocal = sessionmaker(bind=test_engine)
    session = SessionLocal()

    subjects = [
        AccountSubject(subject_code="1001", subject_name="库存现金",     subject_type="资产", direction="DEBIT"),
        AccountSubject(subject_code="1002", subject_name="银行存款",     subject_type="资产", direction="DEBIT"),
        AccountSubject(subject_code="1012", subject_name="其他货币资金", subject_type="资产", direction="DEBIT"),
        AccountSubject(subject_code="2241", subject_name="其他应付款",   subject_type="负债", direction="CREDIT"),
        AccountSubject(subject_code="6001", subject_name="主营业务收入", subject_type="收入", direction="CREDIT"),
        AccountSubject(subject_code="6601", subject_name="销售费用",     subject_type="费用", direction="DEBIT"),
        AccountSubject(subject_code="6602", subject_name="管理费用",     subject_type="费用", direction="DEBIT"),
    ]
    session.bulk_save_objects(subjects)
    session.commit()
    session.close()
    return SessionLocal


@pytest.fixture
def client(test_engine, seeded_session_factory):
    def override_get_db():
        db = seeded_session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


SAMPLE_LLM_RESPONSE = json.dumps({
    "amount": 800,
    "currency": "CNY",
    "expense_type": "招待费",
    "payment_method": "员工垫付",
    "payer_name": "张三",
    "counterparty": None,
    "memo": "招待客户餐费",
    "confidence": 0.95,
})


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestCreateRecord:
    def test_success_returns_201(self, client):
        with patch("ai.llm_client.LLMClient.extract_business_data",
                   return_value=SAMPLE_LLM_RESPONSE):
            resp = client.post("/api/records", json={"raw_text": "今天请客户吃饭花了800元，张三垫付"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "PROCESSED"
        assert data["record_id"] is not None

    def test_empty_text_returns_422(self, client):
        resp = client.post("/api/records", json={"raw_text": "   "})
        assert resp.status_code == 422

    def test_llm_failure_returns_422(self, client):
        from ai.llm_client import LLMClientError
        with patch("ai.llm_client.LLMClient.extract_business_data",
                   side_effect=LLMClientError("timeout")):
            resp = client.post("/api/records", json={"raw_text": "差旅费1000元"})
        assert resp.status_code == 422

    def test_llm_bad_json_returns_422(self, client):
        with patch("ai.llm_client.LLMClient.extract_business_data",
                   return_value="这根本不是JSON"):
            resp = client.post("/api/records", json={"raw_text": "差旅费1000元"})
        assert resp.status_code == 422

    def test_llm_hallucinated_zero_amount_returns_422(self, client):
        bad_json = json.dumps({
            "amount": 0, "expense_type": "招待费",
            "payment_method": "现金", "memo": "x", "confidence": 0.9
        })
        with patch("ai.llm_client.LLMClient.extract_business_data",
                   return_value=bad_json):
            resp = client.post("/api/records", json={"raw_text": "test"})
        assert resp.status_code == 422


class TestGetRecord:
    def test_get_existing_record(self, client):
        with patch("ai.llm_client.LLMClient.extract_business_data",
                   return_value=SAMPLE_LLM_RESPONSE):
            create_resp = client.post("/api/records", json={"raw_text": "测试查询"})
        record_id = create_resp.json()["record_id"]

        resp = client.get(f"/api/records/{record_id}")
        assert resp.status_code == 200
        assert resp.json()["record_id"] == record_id

    def test_get_nonexistent_returns_404(self, client):
        resp = client.get("/api/records/999999")
        assert resp.status_code == 404


class TestListRecords:
    def test_list_returns_200(self, client):
        resp = client.get("/api/records")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_list_filter_by_status(self, client):
        resp = client.get("/api/records?status=PROCESSED")
        assert resp.status_code == 200
        for item in resp.json():
            assert item["status"] == "PROCESSED"
