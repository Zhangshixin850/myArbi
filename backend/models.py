import time
import uuid
from sqlalchemy import JSON, BigInteger, ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def now_ms():
    return time.time_ns() // 1_000_000


class Base(DeclarativeBase):
    pass


class Card(Base):
    __tablename__ = 'cards'
    id: Mapped[str] = mapped_column(primary_key=True, default=lambda: uuid.uuid4().hex)
    base: Mapped[str]
    status: Mapped[str] = mapped_column(default='active')
    started_at: Mapped[int] = mapped_column(BigInteger, default=now_ms)
    closed_at: Mapped[int | None] = mapped_column(BigInteger)
    zero_since: Mapped[int | None] = mapped_column(BigInteger)
    revised_at: Mapped[int] = mapped_column(BigInteger, default=now_ms)
    legs: Mapped[list['Leg']] = relationship(cascade='all, delete-orphan')


class Leg(Base):
    __tablename__ = 'legs'
    id: Mapped[int] = mapped_column(primary_key=True)
    card_id: Mapped[str] = mapped_column(ForeignKey('cards.id'))
    account: Mapped[str]
    product: Mapped[str]
    symbol: Mapped[str]
    direction: Mapped[str]
    # BOTH reserves the whole instrument in one-way mode.
    reservation: Mapped[str]
    reserved: Mapped[bool] = mapped_column(default=True)
    baseline: Mapped[dict] = mapped_column(JSON, default=dict)
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    synced_at: Mapped[int | None] = mapped_column(BigInteger)
    error: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (Index('uq_active_leg', 'account', 'product', 'symbol', 'reservation', unique=True,
                           sqlite_where=text('reserved = 1')),)


class Event(Base):
    __tablename__ = 'events'
    id: Mapped[int] = mapped_column(primary_key=True)
    leg_id: Mapped[int] = mapped_column(ForeignKey('legs.id'))
    account: Mapped[str]
    product: Mapped[str]
    symbol: Mapped[str]
    kind: Mapped[str]
    external_id: Mapped[str]
    time: Mapped[int] = mapped_column(BigInteger)
    data: Mapped[dict] = mapped_column(JSON)
    raw: Mapped[dict] = mapped_column(JSON)
    __table_args__ = (UniqueConstraint('account', 'product', 'symbol', 'kind', 'external_id'),)


class Cursor(Base):
    __tablename__ = 'cursors'
    key: Mapped[str] = mapped_column(primary_key=True)
    through: Mapped[int] = mapped_column(BigInteger)
    audited_at: Mapped[int] = mapped_column(BigInteger, default=0)


class Snapshot(Base):
    __tablename__ = 'snapshots'
    id: Mapped[int] = mapped_column(primary_key=True)
    leg_id: Mapped[int] = mapped_column(ForeignKey('legs.id'))
    time: Mapped[int] = mapped_column(BigInteger, index=True)
    data: Mapped[dict] = mapped_column(JSON)


class Audit(Base):
    __tablename__ = 'audit'
    id: Mapped[int] = mapped_column(primary_key=True)
    card_id: Mapped[str]
    time: Mapped[int] = mapped_column(BigInteger, default=now_ms)
    message: Mapped[str]
