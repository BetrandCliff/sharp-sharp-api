from datetime import datetime, timezone

import jwt
from fastapi import APIRouter, Depends, HTTPException, Response, WebSocket, WebSocketDisconnect, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.auth_routes import get_current_user
from app.database import get_db
from app.domain_models import Call, Company, Conversation, Driver, Message, User
from app.domain_schemas import (
    CallInput,
    CallResponse,
    CallStatusUpdate,
    ConversationInput,
    ConversationResponse,
    MessageInput,
    MessageResponse,
    MessageUpdate,
)
from app.realtime import realtime
from app.security import decode_access_token

router = APIRouter(tags=["chat and calls"])


def _conversation_for_user(db: Session, conversation_id: str, user: User) -> Conversation:
    conversation = db.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    is_user = conversation.user_id == user.id
    is_company = False
    if conversation.company_id:
        company = db.get(Company, conversation.company_id)
        is_company = company is not None and company.auth_id == user.id
    driver = db.scalar(select(Driver).where(Driver.id == conversation.driver_id))
    is_driver = driver is not None and driver.auth_id == user.id
    if not (is_user or is_company or is_driver):
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


def _call_for_user(db: Session, call_id: str, user: User) -> Call:
    call = db.get(Call, call_id)
    if call is None or user.id not in {call.caller_id, call.receiver_id}:
        raise HTTPException(status_code=404, detail="Call not found")
    return call


def _websocket_user(
    websocket: WebSocket,
    db: Session = Depends(get_db),
) -> User | None:
    token = websocket.query_params.get("token")
    if not token:
        return None
    try:
        payload = decode_access_token(token)
    except (jwt.PyJWTError, RuntimeError):
        return None
    user = db.get(User, str(payload["sub"]))
    if user is None or not user.is_email_verified:
        return None
    return user


@router.post("/conversations", response_model=ConversationResponse, status_code=201)
def create_conversation(
    request: ConversationInput,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Conversation:
    driver = db.get(Driver, request.driver_id)
    if driver is None:
        raise HTTPException(status_code=404, detail="Driver not found")
    if user.role == "driver":
        if driver.auth_id != user.id or request.user_id is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        if db.get(User, request.user_id) is None:
            raise HTTPException(status_code=404, detail="Client not found")
        existing = db.scalar(
            select(Conversation).where(
                Conversation.user_id == request.user_id,
                Conversation.driver_id == driver.id,
            )
        )
        if existing is not None:
            return existing
        conversation = Conversation(
            user_id=request.user_id,
            driver_id=driver.id,
        )
        db.add(conversation)
        db.commit()
        db.refresh(conversation)
        return conversation
    if request.company_id:
        company = db.get(Company, request.company_id)
        if company is None or company.auth_id != user.id:
            raise HTTPException(status_code=404, detail="Company not found")
        existing = db.scalar(
            select(Conversation).where(
                Conversation.company_id == company.id,
                Conversation.driver_id == driver.id,
            )
        )
        if existing is not None:
            return existing
        conversation = Conversation(company_id=company.id, driver_id=driver.id)
    else:
        if request.user_id is not None and request.user_id != user.id:
            raise HTTPException(status_code=403, detail="Not allowed to create this conversation")
        existing = db.scalar(
            select(Conversation).where(
                Conversation.user_id == user.id,
                Conversation.driver_id == driver.id,
            )
        )
        if existing is not None:
            return existing
        conversation = Conversation(user_id=user.id, driver_id=driver.id)
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


@router.get("/conversations", response_model=list[ConversationResponse])
def list_conversations(
    company_id: str | None = None,
    driver_id: str | None = None,
    user_id: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Conversation]:
    query = select(Conversation)
    if user_id:
        driver = db.scalar(select(Driver).where(Driver.auth_id == user.id))
        if driver is None:
            raise HTTPException(status_code=403, detail="Not allowed to read driver conversations")
        query = query.where(
            Conversation.driver_id == driver.id,
            Conversation.user_id == user_id,
        )
    elif company_id:
        company = db.get(Company, company_id)
        if company is None or company.auth_id != user.id:
            raise HTTPException(status_code=403, detail="Not allowed to read company conversations")
        query = query.where(Conversation.company_id == company_id)
    elif driver_id:
        driver = db.get(Driver, driver_id)
        if driver is None or driver.auth_id != user.id:
            raise HTTPException(status_code=403, detail="Not allowed to read driver conversations")
        query = query.where(Conversation.driver_id == driver_id)
    else:
        query = query.where(Conversation.user_id == user.id)
    return list(db.scalars(query.order_by(Conversation.created_at.desc())).all())


@router.get("/conversations/{conversation_id}", response_model=ConversationResponse)
def get_conversation(
    conversation_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Conversation:
    return _conversation_for_user(db, conversation_id, user)


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageResponse])
def list_messages(
    conversation_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Message]:
    _conversation_for_user(db, conversation_id, user)
    return list(
        db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc())
        ).all()
    )


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_message(
    conversation_id: str,
    request: MessageInput,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Message:
    _conversation_for_user(db, conversation_id, user)
    if request.reply_to_message_id:
        reply = db.get(Message, request.reply_to_message_id)
        if reply is None or reply.conversation_id != conversation_id:
            raise HTTPException(status_code=400, detail="Reply message is not in this conversation")
    if request.message_type == "text" and not request.message.strip():
        raise HTTPException(status_code=422, detail="Message cannot be empty")
    message = Message(
        conversation_id=conversation_id,
        sender_id=user.id,
        sender_type=request.sender_type,
        message=request.message.strip(),
        message_type=request.message_type,
        audio_url=request.audio_url,
        audio_duration=request.audio_duration,
        reply_to_message_id=request.reply_to_message_id,
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    await realtime.publish(
        f"conversation:{conversation_id}",
        {"event": "insert", "record": MessageResponse.model_validate(message).model_dump(mode="json")},
    )
    return message


@router.patch("/messages/{message_id}", response_model=MessageResponse)
async def update_message(
    message_id: str,
    request: MessageUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Message:
    message = db.get(Message, message_id)
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found")
    _conversation_for_user(db, message.conversation_id, user)
    changes = request.model_dump(exclude_unset=True)
    if set(changes) - {"is_read"} and message.sender_id != user.id:
        raise HTTPException(status_code=403, detail="Only the sender can edit or delete a message")
    if "message" in changes:
        if changes["message"] is None or not changes["message"].strip():
            raise HTTPException(status_code=422, detail="Message cannot be empty")
        changes["message"] = changes["message"].strip()
        message.is_edited = True
    if changes.get("is_deleted"):
        message.message = ""
        message.is_deleted = True
    for key, value in changes.items():
        setattr(message, key, value)
    message.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(message)
    await realtime.publish(
        f"conversation:{message.conversation_id}",
        {"event": "update", "record": MessageResponse.model_validate(message).model_dump(mode="json")},
    )
    return message


@router.delete("/messages/{message_id}", status_code=status.HTTP_204_NO_CONTENT)
async def permanently_delete_message(
    message_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    message = db.get(Message, message_id)
    if message is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    _conversation_for_user(db, message.conversation_id, user)
    if message.sender_id != user.id:
        raise HTTPException(status_code=403, detail="Only the sender can delete a message")
    conversation_id = message.conversation_id
    db.delete(message)
    db.commit()
    await realtime.publish(
        f"conversation:{conversation_id}",
        {"event": "delete", "record": {"id": message_id}},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.websocket("/ws/conversations/{conversation_id}")
async def conversation_socket(
    websocket: WebSocket,
    conversation_id: str,
    db: Session = Depends(get_db),
    user: User | None = Depends(_websocket_user),
) -> None:
    if user is None:
        await websocket.close(code=4401)
        return
    try:
        _conversation_for_user(db, conversation_id, user)
    except HTTPException:
        await websocket.close(code=4403)
        return
    await websocket.accept()
    topic = f"conversation:{conversation_id}"
    realtime.connect(topic, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        realtime.disconnect(topic, websocket)


@router.post("/calls", response_model=CallResponse, status_code=201)
def create_call(
    request: CallInput,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Call:
    receiver_id = request.receiver_id
    if db.get(User, receiver_id) is None:
        driver = db.get(Driver, receiver_id)
        if driver is None or driver.auth_id is None:
            raise HTTPException(status_code=404, detail="Call recipient not found")
        receiver_id = driver.auth_id
    if request.conversation_id:
        conversation = _conversation_for_user(db, request.conversation_id, user)
        if receiver_id == user.id:
            raise HTTPException(status_code=400, detail="Cannot call yourself")
        if receiver_id not in {conversation.user_id, conversation.company_id}:
            driver = db.get(Driver, conversation.driver_id)
            if driver is None or driver.auth_id != receiver_id:
                raise HTTPException(status_code=403, detail="Recipient is not in this conversation")
    call = Call(
        conversation_id=request.conversation_id,
        order_id=request.order_id,
        caller_id=user.id,
        receiver_id=receiver_id,
        status="ringing",
    )
    db.add(call)
    db.commit()
    db.refresh(call)
    return call


@router.get("/calls", response_model=list[CallResponse])
def list_calls(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Call]:
    return list(
        db.scalars(
            select(Call)
            .where(or_(Call.caller_id == user.id, Call.receiver_id == user.id))
            .order_by(Call.created_at.desc())
        ).all()
    )


@router.get("/calls/{call_id}", response_model=CallResponse)
def get_call(
    call_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Call:
    return _call_for_user(db, call_id, user)


@router.patch("/calls/{call_id}", response_model=CallResponse)
def update_call(
    call_id: str,
    request: CallStatusUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Call:
    call = _call_for_user(db, call_id, user)
    now = datetime.now(timezone.utc)
    call.status = request.status
    if request.status in {"accepted", "connected"} and call.answered_at is None:
        call.answered_at = now
        call.started_at = now
    if request.status in {"ended", "rejected", "cancelled", "missed", "failed"}:
        call.ended_at = now
    if request.duration_seconds is not None:
        call.duration_seconds = request.duration_seconds
    db.commit()
    db.refresh(call)
    return call


@router.websocket("/ws/calls/{call_id}")
async def call_socket(
    websocket: WebSocket,
    call_id: str,
    db: Session = Depends(get_db),
    user: User | None = Depends(_websocket_user),
) -> None:
    if user is None:
        await websocket.close(code=4401)
        return
    call = db.get(Call, call_id)
    if call is None or user.id not in {call.caller_id, call.receiver_id}:
        await websocket.close(code=4403)
        return
    await websocket.accept()
    topic = f"call:{call_id}"
    realtime.connect(topic, websocket)
    try:
        while True:
            event = await websocket.receive_json()
            if not isinstance(event, dict) or event.get("event") != "webrtc":
                await websocket.send_json({"event": "error", "detail": "invalid_event"})
                continue
            await realtime.publish(topic, {"event": "webrtc", "call_id": call_id, "data": event.get("data", {})})
    except WebSocketDisconnect:
        realtime.disconnect(topic, websocket)
