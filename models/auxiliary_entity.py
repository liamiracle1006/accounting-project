from sqlalchemy import String, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from database.connection import Base
from models.mixins import TenantMixin


class AuxiliaryEntity(TenantMixin, Base):
    __tablename__ = "auxiliary_entity"

    entity_id:   Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(String(20),  nullable=False)
    entity_name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_active:   Mapped[int] = mapped_column(default=1)
    created_at   = mapped_column(DateTime, server_default=func.now())

    def __repr__(self) -> str:
        return f"<AuxiliaryEntity {self.entity_id} [{self.entity_type}] {self.entity_name}>"
