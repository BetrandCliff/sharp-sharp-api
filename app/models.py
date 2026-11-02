from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Delivery(Base):
    __tablename__ = "deliveries"

    delivery_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    locations: Mapped[list["DeliveryLocationRecord"]] = relationship(
        back_populates="delivery", cascade="all, delete-orphan"
    )


class DeliveryLocationRecord(Base):
    __tablename__ = "delivery_locations"
    __table_args__ = (
        Index("ix_delivery_locations_delivery_updated", "delivery_id", "updated_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    delivery_id: Mapped[str] = mapped_column(
        ForeignKey("deliveries.delivery_id", ondelete="CASCADE"), nullable=False
    )
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lng: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )
    delivery: Mapped[Delivery] = relationship(back_populates="locations")


from app import domain_models as _domain_models
