from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.auth_routes import get_current_user
from app.chat_routes import _websocket_user
from app.database import get_db
from app.domain_models import (
    Activity,
    Company,
    Driver,
    ErrantItem,
    ErrantOrder,
    GasOrder,
    User,
)
from app.domain_schemas import (
    ActivityInput,
    ActivityResponse,
    CompanyResponse,
    DriverResponse,
    ErrantInput,
    ErrantResponse,
    ErrantUpdate,
    GasOrderInput,
    GasOrderResponse,
    GasOrderUpdate,
)
from app.realtime import realtime
from fastapi import WebSocket, WebSocketDisconnect

router = APIRouter(tags=["orders and delivery"])


def _errant_query():
    return select(ErrantOrder).options(selectinload(ErrantOrder.items))


def _gas_order_response(order: GasOrder, db: Session) -> GasOrderResponse:
    supplier = db.get(Company, order.supplier_id) if order.supplier_id else None
    payload = {
        "id": order.id,
        "user_id": order.user_id,
        "bottle": order.bottle,
        "color": order.color,
        "quantity": order.quantity,
        "time": order.time,
        "destination": order.destination,
        "status": order.status,
        "payment_method": order.payment_method,
        "price": order.price,
        "supplier_id": order.supplier_id,
        "driver_id": order.driver_id,
        "supplier": CompanyResponse.model_validate(supplier) if supplier else None,
    }
    return GasOrderResponse.model_validate(payload)


def _is_assigned_driver(user: User, driver_id: str | None, db: Session) -> bool:
    if driver_id is None:
        return False
    return db.scalar(
        select(Driver.id).where(Driver.id == driver_id, Driver.auth_id == user.id)
    ) is not None


def _ensure_order_access(order: GasOrder | ErrantOrder | None, user: User, db: Session) -> None:
    if order is None or (
        order.user_id != user.id
        and not _is_assigned_driver(user, order.driver_id, db)
    ):
        raise HTTPException(status_code=404, detail="Order not found")


@router.websocket("/ws/orders/{order_id}")
async def order_socket(
    websocket: WebSocket,
    order_id: str,
    db: Session = Depends(get_db),
    user: User | None = Depends(_websocket_user),
) -> None:
    if user is None:
        await websocket.close(code=4401)
        return
    order = db.get(GasOrder, order_id) or db.get(ErrantOrder, order_id)
    try:
        _ensure_order_access(order, user, db)
    except HTTPException:
        await websocket.close(code=4403)
        return

    await websocket.accept()
    topic = f"order:{order_id}"
    realtime.connect(topic, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        realtime.disconnect(topic, websocket)


@router.get("/companies/suppliers", response_model=list[CompanyResponse])
def list_suppliers(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Company]:
    return list(
        db.scalars(
            select(Company)
            .where(Company.role != "admin")
            .order_by(Company.company_name)
        ).all()
    )


@router.get("/drivers/{driver_id}", response_model=DriverResponse)
def get_driver(
    driver_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Driver:
    driver = db.get(Driver, driver_id)
    if driver is None:
        raise HTTPException(status_code=404, detail="Driver not found")
    return driver


@router.get("/errants", response_model=list[ErrantResponse])
def list_errants(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ErrantOrder]:
    return list(
        db.scalars(
            _errant_query()
            .where(ErrantOrder.user_id == user.id)
            .order_by(ErrantOrder.created_at.desc())
        ).all()
    )


@router.post("/errants", response_model=ErrantResponse, status_code=status.HTTP_201_CREATED)
async def create_errant(
    request: ErrantInput,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ErrantOrder:
    order = ErrantOrder(
        title=request.title,
        fee=request.fee,
        location=request.location,
        latitude=request.latitude,
        longitude=request.longitude,
        time=request.time,
        user_name=request.user_name,
        status=request.status,
        tel=request.tel,
        user_id=user.id,
        items=[ErrantItem(**item.model_dump()) for item in request.items],
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    db.refresh(order, attribute_names=["items"])
    await realtime.publish(
        f"order:{order.id}",
        {"event": "created", "record": ErrantResponse.model_validate(order).model_dump(mode="json", by_alias=True)},
    )
    return order


@router.get("/errants/{order_id}", response_model=ErrantResponse)
def get_errant(
    order_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ErrantOrder:
    order = db.scalar(_errant_query().where(ErrantOrder.id == order_id))
    if order is None or order.user_id != user.id:
        raise HTTPException(status_code=404, detail="Errant order not found")
    return order


@router.patch("/errants/{order_id}", response_model=ErrantResponse)
async def update_errant(
    order_id: str,
    request: ErrantUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ErrantOrder:
    order = db.scalar(_errant_query().where(ErrantOrder.id == order_id))
    if order is None or order.user_id != user.id:
        raise HTTPException(status_code=404, detail="Errant order not found")
    changes = request.model_dump(exclude_unset=True)
    if set(changes) & {"driver_id", "company_id"} and user.role != "admin":
        raise HTTPException(status_code=403, detail="Only an administrator can assign an errant order")
    items = changes.pop("items", None)
    for key, value in changes.items():
        setattr(order, key, value)
    if items is not None:
        order.items = [ErrantItem(**item.model_dump()) for item in items]
    db.commit()
    db.refresh(order)
    await realtime.publish(
        f"order:{order.id}",
        {"event": "updated", "record": ErrantResponse.model_validate(order).model_dump(mode="json", by_alias=True)},
    )
    return order


@router.delete("/errants/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_errant(
    order_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    order = db.get(ErrantOrder, order_id)
    if order is None or order.user_id != user.id:
        raise HTTPException(status_code=404, detail="Errant order not found")
    await realtime.publish(f"order:{order.id}", {"event": "deleted", "id": order.id})
    db.delete(order)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/gas-orders", response_model=list[GasOrderResponse])
def list_gas_orders(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[GasOrderResponse]:
    orders = db.scalars(
        select(GasOrder)
        .where(GasOrder.user_id == user.id)
        .order_by(GasOrder.created_at.desc())
    ).all()
    return [_gas_order_response(order, db) for order in orders]


@router.post("/gas-orders", response_model=GasOrderResponse, status_code=status.HTTP_201_CREATED)
async def create_gas_order(
    request: GasOrderInput,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> GasOrderResponse:
    if db.get(Company, request.supplier_id) is None:
        raise HTTPException(status_code=404, detail="Supplier not found")
    order = GasOrder(
        user_id=user.id,
        supplier_id=request.supplier_id,
        bottle=request.bottle,
        color=request.color,
        quantity=request.quantity,
        time=request.time,
        destination=request.destination,
        status=request.status,
        payment_method=request.payment_method,
        price=request.price,
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    response = _gas_order_response(order, db)
    await realtime.publish(
        f"order:{order.id}",
        {"event": "created", "record": response.model_dump(mode="json", by_alias=True)},
    )
    return response


@router.get("/gas-orders/{order_id}", response_model=GasOrderResponse)
def get_gas_order(
    order_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> GasOrderResponse:
    order = db.get(GasOrder, order_id)
    if order is None or (
        order.user_id != user.id and not _is_assigned_driver(user, order.driver_id, db)
    ):
        raise HTTPException(status_code=404, detail="Gas order not found")
    return _gas_order_response(order, db)


@router.patch("/gas-orders/{order_id}", response_model=GasOrderResponse)
async def update_gas_order(
    order_id: str,
    request: GasOrderUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> GasOrderResponse:
    order = db.get(GasOrder, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Gas order not found")
    is_owner = order.user_id == user.id
    is_driver = _is_assigned_driver(user, order.driver_id, db)
    if not is_owner and not is_driver:
        raise HTTPException(status_code=404, detail="Gas order not found")
    changes = request.model_dump(exclude_unset=True)
    if is_driver and not is_owner and set(changes) - {"status"}:
        raise HTTPException(status_code=403, detail="Drivers can only update order status")
    if set(changes) & {"driver_id"} and user.role != "admin":
        raise HTTPException(status_code=403, detail="Only an administrator can assign a driver")
    if "supplier_id" in changes and changes["supplier_id"]:
        if db.get(Company, changes["supplier_id"]) is None:
            raise HTTPException(status_code=404, detail="Supplier not found")
    for key, value in changes.items():
        setattr(order, key, value)
    db.commit()
    db.refresh(order)
    response = _gas_order_response(order, db)
    await realtime.publish(
        f"order:{order.id}",
        {"event": "updated", "record": response.model_dump(mode="json", by_alias=True)},
    )
    return response


@router.delete("/gas-orders/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_gas_order(
    order_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    order = db.get(GasOrder, order_id)
    if order is None or order.user_id != user.id:
        raise HTTPException(status_code=404, detail="Gas order not found")
    await realtime.publish(f"order:{order.id}", {"event": "deleted", "id": order.id})
    db.delete(order)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/activities", response_model=list[ActivityResponse])
def list_activities(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Activity]:
    return list(
        db.scalars(
            select(Activity)
            .where(Activity.user_id == user.id)
            .order_by(Activity.created_at.desc())
        ).all()
    )


@router.post("/activities", response_model=ActivityResponse, status_code=status.HTTP_201_CREATED)
def create_activity(
    request: ActivityInput,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Activity:
    activity = Activity(**request.model_dump(), user_id=user.id)
    db.add(activity)
    db.commit()
    db.refresh(activity)
    return activity


@router.get("/activities/{reference_id}", response_model=ActivityResponse | None)
def get_activity(
    reference_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Activity | None:
    return db.scalar(
        select(Activity).where(
            Activity.reference_id == reference_id,
            Activity.user_id == user.id,
        )
    )


@router.patch("/activities/{reference_id}", response_model=ActivityResponse)
def update_activity(
    reference_id: str,
    request: ActivityInput,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Activity:
    activity = db.scalar(
        select(Activity).where(
            Activity.reference_id == reference_id,
            Activity.user_id == user.id,
        )
    )
    if activity is None:
        raise HTTPException(status_code=404, detail="Activity not found")
    for key, value in request.model_dump().items():
        setattr(activity, key, value)
    db.commit()
    db.refresh(activity)
    return activity


@router.delete("/activities/{activity_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_activity(
    activity_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    activity = db.scalar(
        select(Activity).where(Activity.id == activity_id, Activity.user_id == user.id)
    )
    if activity is None:
        raise HTTPException(status_code=404, detail="Activity not found")
    db.delete(activity)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
