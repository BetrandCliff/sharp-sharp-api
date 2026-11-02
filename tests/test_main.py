import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.domain_models import Company, Driver, GasOrder, User
from app.main import app
from app.security import create_access_token


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "test-jwt-secret-that-is-long-enough-for-tests")
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session_local = sessionmaker(bind=engine, expire_on_commit=False)

    def override_get_db():
        with testing_session_local() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    with testing_session_local() as session:
        user = User(email="api@example.com", password_hash="unused", is_email_verified=True)
        receiver = User(email="receiver@example.com", password_hash="unused", is_email_verified=True)
        session.add_all([user, receiver])
        session.flush()
        company = Company(auth_id=user.id, company_name="Test supplier", role="supplier")
        session.add(company)
        session.flush()
        driver = Driver(auth_id=receiver.id, company_id=company.id, name="Test driver")
        session.add(driver)
        session.flush()
        order = GasOrder(
            user_id=user.id,
            supplier_id=company.id,
            driver_id=driver.id,
            bottle="12.5kg",
            color=0,
            quantity=1,
            time="now",
            destination="home",
            status="assigned",
            payment_method="cash",
            price=10,
        )
        session.add(order)
        session.commit()
        user_id = user.id
        receiver_id = receiver.id
        driver_id = driver.id
        delivery_id = order.id
    with TestClient(app) as test_client:
        user_token, _ = create_access_token(user_id)
        receiver_token, _ = create_access_token(receiver_id)
        test_client.headers["Authorization"] = f"Bearer {user_token}"
        test_client.headers["X-Test-User-ID"] = user_id
        test_client.headers["X-Test-Receiver-ID"] = receiver_id
        test_client.headers["X-Test-Receiver-Token"] = receiver_token
        test_client.headers["X-Test-Driver-ID"] = driver_id
        test_client.headers["X-Test-Delivery-ID"] = delivery_id
        test_client.headers["X-Test-User-Token"] = user_token
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_health_check(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_location_update_and_readback(client: TestClient) -> None:
    delivery_id = client.headers["X-Test-Delivery-ID"]
    payload = {"deliveryId": delivery_id, "lat": 5.6037, "lng": -0.1870}

    client.headers["Authorization"] = f"Bearer {client.headers['X-Test-Receiver-Token']}"
    update = client.post("/delivery/update-location", json=payload)
    client.headers["Authorization"] = f"Bearer {client.headers['X-Test-User-Token']}"
    readback = client.get(f"/delivery/{delivery_id}/location")

    assert update.status_code == 200
    assert update.json()["deliveryId"] == payload["deliveryId"]
    assert update.json()["lat"] == payload["lat"]
    assert readback.json() == update.json()


def test_location_history_is_persisted(client: TestClient) -> None:
    delivery_id = client.headers["X-Test-Delivery-ID"]
    client.headers["Authorization"] = f"Bearer {client.headers['X-Test-Receiver-Token']}"
    client.post(
        "/delivery/update-location",
        json={"deliveryId": delivery_id, "lat": 5.1, "lng": -0.1},
    )
    client.post(
        "/delivery/update-location",
        json={"deliveryId": delivery_id, "lat": 5.2, "lng": -0.2},
    )

    client.headers["Authorization"] = f"Bearer {client.headers['X-Test-User-Token']}"
    history = client.get(f"/delivery/{delivery_id}/locations")
    latest = client.get(f"/delivery/{delivery_id}/location")

    assert history.status_code == 200
    assert len(history.json()) == 2
    assert history.json()[-1]["lat"] == 5.2
    assert latest.json()["lat"] == 5.2


def test_location_update_reaches_websocket_subscriber(client: TestClient) -> None:
    delivery_id = client.headers["X-Test-Delivery-ID"]
    payload = {"deliveryId": delivery_id, "lat": 5.6037, "lng": -0.1870}

    socket_url = f"/ws/delivery/{delivery_id}?token={client.headers['X-Test-User-Token']}"
    with client.websocket_connect(socket_url) as subscriber:
        client.headers["Authorization"] = f"Bearer {client.headers['X-Test-Receiver-Token']}"
        response = client.post("/delivery/update-location", json=payload)

        assert response.status_code == 200
        assert subscriber.receive_json()["deliveryId"] == payload["deliveryId"]


def test_payment_intent_requires_stripe_configuration(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)

    response = client.post(
        "/payment/intent",
        json={"amount": 1000, "currency": "usd"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Payment service is not configured"


def test_payment_intent_is_persisted(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeIntent:
        id = "pi_test_123"
        client_secret = "pi_test_secret"
        status = "requires_payment_method"

    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_fake")
    monkeypatch.setattr(
        "app.main.stripe.PaymentIntent.create",
        lambda **kwargs: FakeIntent(),
    )

    response = client.post(
        "/payment/intent",
        json={"amount": 1000, "currency": "usd", "order_id": "order-1"},
    )

    assert response.status_code == 200
    assert response.json()["clientSecret"] == "pi_test_secret"
    payments = client.get("/payments").json()
    assert payments[0]["provider_payment_id"] == "pi_test_123"
    assert payments[0]["order_id"] == "order-1"


def test_admin_catalog_endpoints_reject_regular_users(client: TestClient) -> None:
    response = client.get("/admin/companies")

    assert response.status_code == 403


def test_websocket_relays_signaling_message(client: TestClient) -> None:
    caller_id = client.headers["X-Test-User-ID"]
    receiver_id = client.headers["X-Test-Receiver-ID"]
    caller_token = client.headers["X-Test-User-Token"]
    receiver_token = client.headers["X-Test-Receiver-Token"]
    offer = {"type": "offer", "from": "spoofed", "to": receiver_id, "sdp": "test-sdp"}

    with client.websocket_connect(f"/ws/signaling?token={caller_token}") as caller:
        with client.websocket_connect(f"/ws/signaling?token={receiver_token}") as receiver:
            caller.send_json({"type": "register", "userId": caller_id})
            assert caller.receive_json()["type"] == "registered"

            receiver.send_json({"type": "register", "userId": receiver_id})
            assert receiver.receive_json()["type"] == "registered"

            caller.send_json(offer)
            relayed = receiver.receive_json()
            assert relayed["from"] == caller_id
            assert relayed["sdp"] == offer["sdp"]
