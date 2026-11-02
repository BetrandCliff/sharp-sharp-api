import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.domain_models import Company, Driver, User
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
    with testing_session_local() as session:
        user = User(email="buyer@example.com", password_hash="not-used", is_email_verified=True)
        company = Company(company_name="Local Gas", role="supplier")
        session.add_all([user, company])
        session.flush()
        driver = Driver(auth_id=user.id, company_id=company.id, name="Driver One", phone="123")
        session.add(driver)
        session.commit()
        user_id = user.id
        company_id = company.id

    def override_get_db():
        with testing_session_local() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    token, _ = create_access_token(user_id)
    with TestClient(app) as test_client:
        test_client.headers["Authorization"] = f"Bearer {token}"
        test_client.headers["X-Test-Company"] = company_id
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_create_errant_order_persists_items(client: TestClient) -> None:
    response = client.post(
        "/errants",
        json={
            "title": "Pick up groceries",
            "fee": 2500,
            "location": "Central Market",
            "latitude": 3.87,
            "longitude": 11.52,
            "time": "10:00",
            "userName": "Buyer",
            "status": "pending",
            "tel": "+237600000000",
            "items": [{"name": "Rice", "price": 3000, "quantity": 2}],
        },
    )

    assert response.status_code == 201, response.text
    created = response.json()
    assert created["userName"] == "Buyer"
    assert created["items"][0]["name"] == "Rice"
    assert client.get("/errants").json()[0]["id"] == created["id"]


def test_create_gas_order_returns_supplier(client: TestClient) -> None:
    response = client.post(
        "/gas-orders",
        json={
            "bottle": "12.5kg",
            "color": 4294967295,
            "quantity": 1,
            "time": "ASAP",
            "destination": "Home",
            "status": "pending",
            "paymentMethod": "cash",
            "price": 6500,
            "supplier_id": client.headers["X-Test-Company"],
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["supplier"]["company_name"] == "Local Gas"
    assert client.get("/gas-orders").json()[0]["id"] == response.json()["id"]


def test_activity_is_scoped_to_authenticated_user(client: TestClient) -> None:
    response = client.post(
        "/activities",
        json={
            "reference_id": "order-1",
            "type": "gas_order",
            "title": "Gas delivery",
            "route": "Depot to Home",
            "duration": "30 min",
            "time": "10:00",
            "fare": 0,
            "price": 6500,
            "client_name": "Buyer",
            "client_phone": "123",
            "driver_name": "Driver One",
            "driver_phone": "456",
            "status": "completed",
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["reference_id"] == "order-1"
    assert client.get("/activities").json()[0]["user_id"]


def test_audio_upload_url_requires_auth_and_returns_r2_put_contract(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.storage_routes.create_audio_upload",
        lambda user_id, filename, content_type, content_length: (
            "https://r2.example/upload?signature=test",
            f"https://cdn.example/chat-audio/{user_id}/file.m4a",
            f"chat-audio/{user_id}/file.m4a",
            300,
        ),
    )

    response = client.post(
        "/storage/audio/upload-url",
        json={
            "filename": "recording.m4a",
            "content_type": "audio/mp4",
            "content_length": 1024,
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["object_key"].startswith("chat-audio/")
    assert response.json()["content_length"] == 1024
