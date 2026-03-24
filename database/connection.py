"""
AgentLedger — SQLAlchemy engine + session factory
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from config.settings import DATABASE_URL, DB_ECHO


engine = create_engine(
    DATABASE_URL,
    echo=DB_ECHO,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,      # reconnect on stale connections
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""
    pass


def get_db():
    """FastAPI dependency — yields a DB session and guarantees cleanup."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables (used in tests / first-run bootstrap)."""
    from models import account_subject, auxiliary_entity   # noqa: F401 — register models
    from models import operational_record, voucher_header, voucher_line  # noqa: F401
    Base.metadata.create_all(bind=engine)
