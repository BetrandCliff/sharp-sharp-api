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
        buyer = User(email="buyer@example.com", password_hash="unused", is_email_verified=True)
        driver_user = User(email="driver@example.com", password_hash="unused", is_email_verified=True)
        company = Company(company_name="Local Gas", role="supplier", auth_id=buyer.id)
        session.add_all([buyer, driver_user, company])
        session.flush()
        driver = Driver(
            auth_id=driver_user.id,
            company_id=company.id,
            name="Driver One",
            phone="123",
        )
        session.add(driver)
        session.commit()
        buyer_id = buyer.id
        driver_id = driver.id
        company_id = company.id

    def override_get_db():
        with testing_session_local() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    token, _ = create_access_token(buyer_id)
    with TestClient(app) as test_client:
        test_client.headers["Authorization"] = f"Bearer {token}"
        test_client.headers["X-Test-Driver"] = driver_id
        test_client.headers["X-Test-Company"] = company_id
        test_client.headers["X-Test-Token"] = token
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_conversation_messages_and_realtime(client: TestClient) -> None:
    conversation_response = client.post(
        "/conversations",
        json={"driver_id": client.headers["X-Test-Driver"]},
    )
    assert conversation_response.status_code == 201, conversation_response.text
    conversation_id = conversation_response.json()["id"]

    with client.websocket_connect(
        f"/ws/conversations/{conversation_id}?token={client.headers['X-Test-Token']}"
    ) as socket:
        sent = client.post(
            f"/conversations/{conversation_id}/messages",
            json={"sender_type": "client", "message": "On my way"},
        )
        assert sent.status_code == 201, sent.text
        event = socket.receive_json()

    assert event["event"] == "insert"
    assert event["record"]["message"] == "On my way"
    assert client.get(f"/conversations/{conversation_id}/messages").json()[0]["message"] == "On my way"


def test_driver_can_be_called_by_id_and_status_updated(client: TestClient) -> None:
    conversation = client.post(
        "/conversations",
        json={"driver_id": client.headers["X-Test-Driver"]},
    ).json()
    created = client.post(
        "/calls",
        json={
            "receiver_id": client.headers["X-Test-Driver"],
            "conversation_id": conversation["id"],
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "ringing"

    updated = client.patch(
        f"/calls/{created.json()['id']}",
        json={"status": "accepted"},
    )
    assert updated.status_code == 200
    assert updated.json()["answered_at"] is not None
