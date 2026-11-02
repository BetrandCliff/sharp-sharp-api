from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PaymentIntentRequest(BaseModel):
    amount: int = Field(ge=50, le=10_000_000, description="Amount in the smallest currency unit")
    currency: str = Field(min_length=3, max_length=3, pattern="^[a-zA-Z]{3}$")
    order_id: str | None = None


class LocationUpdateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    delivery_id: str = Field(alias="deliveryId", min_length=1, max_length=128)
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class DeliveryLocation(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    delivery_id: str = Field(alias="deliveryId")
    lat: float
    lng: float
    updated_at: datetime = Field(alias="updatedAt")
