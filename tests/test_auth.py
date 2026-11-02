import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import domain_models
from app.database import Base, get_db
from app.main import app


@pytest.fixture(autouse=True)
def configure_jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET_KEY", "test-jwt-secret-that-is-long-enough-for-tests")


@pytest.fixture
def client():
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
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_signup_verification_profile_and_refresh_rotation(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent_codes: list[str] = []
    monkeypatch.setattr(
        "app.auth_routes.send_email_code",
        lambda email, code, purpose: sent_codes.append(code),
    )

    signup = client.post(
        "/auth/register",
        json={"email": "driver@example.com", "password": "delivery-password"},
    )
    assert signup.status_code == 201
    assert len(sent_codes) == 1

    verification = client.post(
        "/auth/verify-email",
        json={"email": "driver@example.com", "code": sent_codes[0]},
    )
    assert verification.status_code == 200
    tokens = verification.json()

    current_user = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert current_user.status_code == 200
    assert current_user.json()["email"] == "driver@example.com"

    profile = client.put(
        "/auth/profile",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
        json={"userName": "Test Driver", "phone": "+237600000000"},
    )
    assert profile.status_code == 200
    assert profile.json()["userName"] == "Test Driver"

    rotated = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert rotated.status_code == 200
    assert rotated.json()["refresh_token"] != tokens["refresh_token"]

    reused = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert reused.status_code == 401


def test_login_rejects_unverified_account(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.auth_routes.send_email_code", lambda *args: None)
    client.post(
        "/auth/register",
        json={"email": "unverified@example.com", "password": "delivery-password"},
    )

    response = client.post(
        "/auth/login",
        json={"email": "unverified@example.com", "password": "delivery-password"},
    )

    assert response.status_code == 403
