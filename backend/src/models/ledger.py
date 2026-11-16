from sqlalchemy import String, JSON, Double, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base
class IngestBatch(Base):
    __tablename__ = 'ingest_batches'
    id: Mapped[int] = mapped_column(primary_key=True)
    month: Mapped[str] = mapped_column(String(7), index=True)
    source: Mapped[str] = mapped_column(String(200), default='manual.json')
    rows: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default='accepted')
    errors: Mapped[list] = mapped_column(JSON, default=list)
    effects: Mapped[list] = mapped_column(JSON, default=list)
    created_by: Mapped[int] = mapped_column(ForeignKey('users.id'))
    created_at: Mapped[float] = mapped_column(Double)
class CumulativeRecord(Base):
    __tablename__ = 'cumulative_records'
    __table_args__ = (UniqueConstraint('month','channel','day',name='uq_cumulative_key'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    month: Mapped[str] = mapped_column(String(7), index=True)
    channel: Mapped[str] = mapped_column(String(80))
    day: Mapped[str] = mapped_column(String(10))
    gross: Mapped[float] = mapped_column(Double)
    refunds: Mapped[float] = mapped_column(Double)
    discount: Mapped[float] = mapped_column(Double)
    recognized_net: Mapped[float] = mapped_column(Double)
    visits: Mapped[int] = mapped_column(Integer)
    batch_id: Mapped[int] = mapped_column(ForeignKey('ingest_batches.id'))
    received_at: Mapped[float] = mapped_column(Double)
class DailyAccount(Base):
    __tablename__ = 'daily_accounts'
    __table_args__ = (UniqueConstraint('month','channel','day',name='uq_daily_key'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    month: Mapped[str] = mapped_column(String(7), index=True)
    channel: Mapped[str] = mapped_column(String(80))
    day: Mapped[str] = mapped_column(String(10))
    gross: Mapped[float | None] = mapped_column(Double, nullable=True)
    refunds: Mapped[float | None] = mapped_column(Double, nullable=True)
    discount: Mapped[float | None] = mapped_column(Double, nullable=True)
    recognized_net: Mapped[float | None] = mapped_column(Double, nullable=True)
    visits: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default='pending')
    trace: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[float] = mapped_column(Double)
class MonthState(Base):
    __tablename__ = 'month_states'
    month: Mapped[str] = mapped_column(String(7), primary_key=True)
    current_dataset_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[float] = mapped_column(Double, default=0)
class PublishOrder(Base):
    __tablename__ = 'publish_orders'
    __table_args__ = (UniqueConstraint('month','batch_no',name='uq_publish_batch'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    month: Mapped[str] = mapped_column(String(7), index=True)
    batch_no: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default='draft')
    error: Mapped[str] = mapped_column(String(1000), default='')
    checks: Mapped[dict] = mapped_column(JSON, default=dict)
    dataset_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey('users.id'))
    created_at: Mapped[float] = mapped_column(Double)
    published_at: Mapped[float | None] = mapped_column(Double, nullable=True)
