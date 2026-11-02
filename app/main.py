import os
from datetime import datetime, timezone

import stripe
from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth_routes import get_current_user
from app.chat_routes import _websocket_user
from app.database import get_db
from app.admin_routes import router as admin_router
from app.auth_routes import router as auth_router
from app.chat_routes import router as chat_router
from app.domain_models import Driver, ErrantOrder, GasOrder, Payment, User
from app.models import Delivery, DeliveryLocationRecord
from app.orders_routes import router as orders_router
from app.realtime import realtime
from app.storage_routes import router as storage_router
from app.schemas import DeliveryLocation, LocationUpdateRequest, PaymentIntentRequest

app = FastAPI(title="Sharp Sharp Delivery API", version="0.1.0")
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(orders_router)
app.include_router(chat_router)
app.include_router(storage_router)

allowed_origins = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "*").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

user_connections: dict[str, set[WebSocket]] = {}
delivery_subscribers: dict[str, set[WebSocket]] = {}


def _delivery_access(delivery_id: str, user: User, db: Session) -> tuple[bool, bool]:
    gas_order = db.get(GasOrder, delivery_id)
    errant_order = db.get(ErrantOrder, delivery_id)
    owner_id = gas_order.user_id if gas_order else (errant_order.user_id if errant_order else None)
    assigned_driver_id = (
        gas_order.driver_id if gas_order else (errant_order.driver_id if errant_order else None)
    )
    if owner_id is None and assigned_driver_id is None:
        return False, False
    assigned_driver = (
        db.scalar(
            select(Driver).where(
                Driver.id == assigned_driver_id,
                Driver.auth_id == user.id,
            )
        )
        if assigned_driver_id
        else None
    )
    return owner_id == user.id, assigned_driver is not None


@app.get("/")
def health_check() -> dict[str, str]:
    return {"status": "ok", "service": "sharp-sharp-delivery-api"}


@app.post("/payment/intent")
def create_payment_intent(
    request: PaymentIntentRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, str]:
    secret_key = os.getenv("STRIPE_SECRET_KEY")
    if not secret_key:
        raise HTTPException(
            status_code=503,
            detail="Payment service is not configured",
        )

    try:
        intent = stripe.PaymentIntent.create(
            amount=request.amount,
            currency=request.currency,
            api_key=secret_key,
        )
    except stripe.StripeError as exc:
        raise HTTPException(
            status_code=502,
            detail="Payment provider could not create the payment intent",
        ) from exc

    db.add(
        Payment(
            user_id=user.id,
            order_id=request.order_id,
            provider_payment_id=intent.id,
            amount=request.amount,
            currency=request.currency.lower(),
            status=intent.status,
        )
    )
    db.commit()
    return {"clientSecret": intent.client_secret, "paymentIntentId": intent.id}


@app.post("/payment/webhook")
async def payment_webhook(request: Request, db: Session = Depends(get_db)) -> dict[str, bool]:
    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET")
    if not webhook_secret:
        raise HTTPException(status_code=503, detail="Payment webhook is not configured")

    signature = request.headers.get("stripe-signature")
    if not signature:
        raise HTTPException(status_code=400, detail="Missing Stripe signature")
    payload = await request.body()
    try:
        event = stripe.Webhook.construct_event(payload, signature, webhook_secret)
    except (ValueError, stripe.SignatureVerificationError) as exc:
        raise HTTPException(status_code=400, detail="Invalid Stripe webhook") from exc

    if event.type.startswith("payment_intent."):
        intent = event.data.object
        payment = db.scalar(
            select(Payment).where(Payment.provider_payment_id == intent.id)
        )
        if payment is not None:
            payment.status = intent.status
            db.commit()
    return {"received": True}


@app.get("/payments")
def list_payments(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict[str, object]]:
    payments = db.scalars(
        select(Payment).where(Payment.user_id == user.id).order_by(Payment.created_at.desc())
    ).all()
    return [
        {
            "id": payment.id,
            "order_id": payment.order_id,
            "provider_payment_id": payment.provider_payment_id,
            "amount": payment.amount,
            "currency": payment.currency,
            "status": payment.status,
            "created_at": payment.created_at,
        }
        for payment in payments
    ]


@app.post("/delivery/update-location", response_model=DeliveryLocation)
async def update_delivery_location(
    request: LocationUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DeliveryLocation:
    _, is_assigned_driver = _delivery_access(request.delivery_id, user, db)
    if not is_assigned_driver:
        raise HTTPException(status_code=404, detail="Assigned delivery not found")

    delivery = db.get(Delivery, request.delivery_id)
    now = datetime.now(timezone.utc)
    if delivery is None:
        delivery = Delivery(
            delivery_id=request.delivery_id,
            created_at=now,
            updated_at=now,
        )
        db.add(delivery)

    delivery.updated_at = now
    location_record = DeliveryLocationRecord(
        delivery_id=request.delivery_id,
        lat=request.lat,
        lng=request.lng,
        updated_at=now,
    )
    db.add(location_record)
    db.commit()
    db.refresh(location_record)
    location = DeliveryLocation(
        deliveryId=location_record.delivery_id,
        lat=location_record.lat,
        lng=location_record.lng,
        updatedAt=location_record.updated_at,
    )

    await realtime.publish(
        f"delivery:{request.delivery_id}",
        location.model_dump(mode="json", by_alias=True),
    )

    return location


@app.get("/delivery/{delivery_id}/location", response_model=DeliveryLocation)
def get_delivery_location(
    delivery_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DeliveryLocation:
    is_owner, is_assigned_driver = _delivery_access(delivery_id, user, db)
    if not (is_owner or is_assigned_driver):
        raise HTTPException(status_code=404, detail="Delivery not found")

    location = db.scalar(
        select(DeliveryLocationRecord)
        .where(DeliveryLocationRecord.delivery_id == delivery_id)
        .order_by(DeliveryLocationRecord.updated_at.desc(), DeliveryLocationRecord.id.desc())
        .limit(1)
    )
    if location is None:
        raise HTTPException(status_code=404, detail="Location not found")
    return DeliveryLocation(
        deliveryId=location.delivery_id,
        lat=location.lat,
        lng=location.lng,
        updatedAt=location.updated_at,
    )


@app.get("/delivery/{delivery_id}/locations", response_model=list[DeliveryLocation])
def get_delivery_location_history(
    delivery_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[DeliveryLocation]:
    is_owner, is_assigned_driver = _delivery_access(delivery_id, user, db)
    if not (is_owner or is_assigned_driver):
        raise HTTPException(status_code=404, detail="Delivery not found")

    locations = db.scalars(
        select(DeliveryLocationRecord)
        .where(DeliveryLocationRecord.delivery_id == delivery_id)
        .order_by(DeliveryLocationRecord.updated_at, DeliveryLocationRecord.id)
    ).all()
    return [
        DeliveryLocation(
            deliveryId=location.delivery_id,
            lat=location.lat,
            lng=location.lng,
            updatedAt=location.updated_at,
        )
        for location in locations
    ]


@app.websocket("/ws/signaling")
async def signaling_socket(
    websocket: WebSocket,
    db: Session = Depends(get_db),
    user: User | None = Depends(_websocket_user),
) -> None:
    if user is None:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    registered_user_id = user.id
    user_connections.setdefault(user.id, set()).add(websocket)

    try:
        while True:
            message = await websocket.receive_json()
            if not isinstance(message, dict):
                await websocket.send_json({"type": "error", "message": "invalid_message"})
                continue

            if message.get("type") == "register":
                if message.get("userId") != user.id:
                    await websocket.close(code=4403)
                    return
                await websocket.send_json({"type": "registered", "userId": user.id})
                continue

            recipient_id = message.get("to")
            if not isinstance(recipient_id, str) or not recipient_id:
                await websocket.send_json({"type": "error", "message": "recipient_required"})
                continue

            recipients = user_connections.get(recipient_id, set())
            if not recipients:
                driver = db.get(Driver, recipient_id)
                if driver is not None and driver.auth_id is not None:
                    recipient_id = driver.auth_id
                    recipients = user_connections.get(recipient_id, set())
            if not recipients:
                await websocket.send_json({"type": "error", "message": "recipient_unavailable"})
                continue

            message["from"] = user.id
            for recipient in tuple(recipients):
                await recipient.send_json(message)
    except WebSocketDisconnect:
        pass
    finally:
        if registered_user_id is not None:
            connections = user_connections.get(registered_user_id)
            if connections is not None:
                connections.discard(websocket)
                if not connections:
                    user_connections.pop(registered_user_id, None)


@app.websocket("/ws/delivery/{delivery_id}")
async def delivery_location_socket(
    websocket: WebSocket,
    delivery_id: str,
    db: Session = Depends(get_db),
    user: User | None = Depends(_websocket_user),
) -> None:
    if user is None:
        await websocket.close(code=4401)
        return
    is_owner, is_assigned_driver = _delivery_access(delivery_id, user, db)
    if not (is_owner or is_assigned_driver):
        await websocket.close(code=4403)
        return

    await websocket.accept()
    topic = f"delivery:{delivery_id}"
    realtime.connect(topic, websocket)

    location = db.scalar(
        select(DeliveryLocationRecord)
        .where(DeliveryLocationRecord.delivery_id == delivery_id)
        .order_by(DeliveryLocationRecord.updated_at.desc(), DeliveryLocationRecord.id.desc())
        .limit(1)
    )
    if location is not None:
        current_location = DeliveryLocation(
            deliveryId=location.delivery_id,
            lat=location.lat,
            lng=location.lng,
            updatedAt=location.updated_at,
        )
        await websocket.send_json(current_location.model_dump(mode="json", by_alias=True))

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        realtime.disconnect(topic, websocket)
