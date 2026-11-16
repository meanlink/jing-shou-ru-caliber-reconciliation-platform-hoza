from sqlalchemy import String, JSON, Double, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base
class Dataset(Base):
    __tablename__ = 'datasets'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    source: Mapped[str] = mapped_column(String(200), default='manual.json')
    records: Mapped[list] = mapped_column(JSON)
    checksum: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[float] = mapped_column(Double)
    kind: Mapped[str] = mapped_column(String(20), default='manual')
    month: Mapped[str | None] = mapped_column(String(7), nullable=True)
    batch_no: Mapped[int | None] = mapped_column(nullable=True)
    publish_order_id: Mapped[int | None] = mapped_column(nullable=True, unique=True)
    superseded: Mapped[bool] = mapped_column(Boolean, default=False)
