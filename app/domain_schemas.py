from datetime import date, datetime
from typing import Literal
from pydantic import AliasChoices, BaseModel, ConfigDict, EmailStr, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class CompanyResponse(ORMModel):
    id: str
    company_name: str
    role: str


class DriverResponse(ORMModel):
    id: str
    name: str
    phone: str
    email: str = ""
    company_id: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    company_role: str | None = None


class DriverTripResponse(BaseModel):
    id: str
    company_id: str | None
    driver_id: str
    created_at: datetime


class DriverDailyStatisticsResponse(BaseModel):
    date: date
    day_name: str
    trip_count: int
    total_earnings: float


class DriverOrderStatusUpdate(BaseModel):
    status: Literal["accepted", "in_progress", "completed", "cancelled"]


class ErrantItemInput(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    price: float = Field(ge=0)
    quantity: int = Field(ge=1)


class ErrantInput(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    fee: float = Field(ge=0)
    location: str = Field(min_length=1)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    time: str = ""
    user_name: str = Field(alias="userName", max_length=160)
    status: str = "pending"
    tel: str = Field(max_length=40)
    items: list[ErrantItemInput] = Field(min_length=1)
    model_config = ConfigDict(populate_by_name=True)


class ErrantUpdate(BaseModel):
    title: str | None = None
    fee: float | None = Field(default=None, ge=0)
    location: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    time: str | None = None
    user_name: str | None = Field(
        default=None,
        validation_alias=AliasChoices("userName", "name", "user_name"),
        serialization_alias="userName",
    )
    status: str | None = None
    tel: str | None = None
    driver_id: str | None = None
    company_id: str | None = None
    items: list[ErrantItemInput] | None = Field(default=None, min_length=1)
    model_config = ConfigDict(populate_by_name=True)


class ErrantItemResponse(ORMModel):
    id: str
    errant_id: str
    name: str
    price: float
    quantity: int


class ErrantResponse(ORMModel):
    id: str
    title: str
    fee: float
    location: str
    latitude: float | None
    longitude: float | None
    time: str
    user_name: str = Field(alias="userName")
    status: str
    tel: str
    user_id: str
    driver_id: str | None
    company_id: str | None
    items: list[ErrantItemResponse] = []


class GasOrderInput(BaseModel):
    bottle: str
    color: int
    quantity: int = Field(ge=1)
    time: str = ""
    destination: str = Field(min_length=1)
    status: str = "pending"
    payment_method: str = Field(alias="paymentMethod")
    price: float = Field(ge=0)
    supplier_id: str
    model_config = ConfigDict(populate_by_name=True)


class GasOrderUpdate(BaseModel):
    bottle: str | None = None
    color: int | None = None
    quantity: int | None = Field(default=None, ge=1)
    time: str | None = None
    destination: str | None = None
    status: str | None = None
    payment_method: str | None = Field(default=None, alias="paymentMethod")
    price: float | None = Field(default=None, ge=0)
    supplier_id: str | None = None
    driver_id: str | None = None
    model_config = ConfigDict(populate_by_name=True)


class GasOrderResponse(ORMModel):
    id: str
    user_id: str
    bottle: str
    color: int
    quantity: int
    time: str
    destination: str
    status: str
    payment_method: str = Field(alias="paymentMethod")
    price: float
    supplier_id: str | None
    driver_id: str | None
    supplier: CompanyResponse | None = None


class ActivityInput(BaseModel):
    reference_id: str
    type: str
    title: str = ""
    route: str = ""
    duration: str = ""
    time: str = ""
    fare: float = 0
    price: float = 0
    client_name: str = ""
    client_phone: str = ""
    driver_name: str = ""
    driver_phone: str = ""
    status: str = ""


class ActivityResponse(ORMModel):
    id: str
    reference_id: str
    type: str
    title: str
    route: str
    duration: str
    time: str
    fare: float
    price: float
    client_name: str
    client_phone: str
    driver_name: str
    driver_phone: str
    status: str
    user_id: str
    created_at: datetime


class ConversationInput(BaseModel):
    driver_id: str
    company_id: str | None = None
    user_id: str | None = None


class ConversationResponse(ORMModel):
    id: str
    user_id: str | None
    company_id: str | None
    driver_id: str
    created_at: datetime


class MessageInput(BaseModel):
    sender_type: str = Field(min_length=1, max_length=40)
    message: str = ""
    message_type: str = "text"
    audio_url: str | None = None
    audio_duration: int | None = Field(default=None, ge=0)
    reply_to_message_id: str | None = None


class MessageUpdate(BaseModel):
    message: str | None = None
    is_read: bool | None = None
    is_deleted: bool | None = None


class MessageResponse(ORMModel):
    id: str
    conversation_id: str
    sender_id: str
    sender_type: str
    message: str
    message_type: str
    audio_url: str | None
    audio_duration: int | None
    reply_to_message_id: str | None
    is_read: bool
    is_edited: bool
    is_deleted: bool
    created_at: datetime
    updated_at: datetime


class CallInput(BaseModel):
    receiver_id: str
    conversation_id: str | None = None
    order_id: str | None = None


class CallStatusUpdate(BaseModel):
    status: str = Field(pattern="^(calling|ringing|connecting|accepted|connected|rejected|ended|failed|cancelled|missed)$")
    duration_seconds: int | None = Field(default=None, ge=0)


class CallResponse(ORMModel):
    id: str
    conversation_id: str | None
    order_id: str | None
    caller_id: str
    receiver_id: str
    status: str
    duration_seconds: int | None
    created_at: datetime
    answered_at: datetime | None
    ended_at: datetime | None


class UploadRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=200)
    content_type: str = Field(pattern="^audio/(mpeg|mp4|wav|webm|aac|ogg|x-m4a)$")
    content_length: int = Field(gt=0)


class UploadResponse(BaseModel):
    upload_url: str
    public_url: str
    object_key: str
    expires_in: int
    content_type: str
    content_length: int
