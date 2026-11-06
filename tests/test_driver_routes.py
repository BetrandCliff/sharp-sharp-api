from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.domain_models import Company, Driver, ErrantOrder, GasOrder, User
from app.main import app
from app.security import create_access_token


@pytest.fixture
def driver_client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "test-jwt-secret-that-is-long-enough-for-tests")
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session_local = sessionmaker(bind=engine, expire_on_commit=False)

    with testing_session_local() as session:
        owner = User(
            email="owner@example.com",
            password_hash="not-used",
            is_email_verified=True,
        )
        driver_user = User(
            email="driver@example.com",
            password_hash="not-used",
            role="driver",
            is_email_verified=True,
        )
        company = Company(company_name="Local Gas", role="supplier")
        session.add_all([owner, driver_user, company])
        session.flush()
        driver = Driver(
            auth_id=driver_user.id,
            company_id=company.id,
            name="Driver One",
            phone="123",
        )
        session.add(driver)
        session.flush()
        gas_order = GasOrder(
            user_id=owner.id,
            supplier_id=company.id,
            driver_id=driver.id,
            bottle="12.5kg",
            color=4294967295,
            quantity=1,
            time="ASAP",
            destination="Home",
            status="in_progress",
            payment_method="cash",
            price=6500,
        )
        errant_order = ErrantOrder(
            title="Grocery delivery",
            fee=2500,
            location="Central Market",
            time="10:00",
            user_name="Owner",
            status="pending",
            tel="123",
            user_id=owner.id,
            driver_id=driver.id,
            company_id=company.id,
        )
        session.add_all([gas_order, errant_order])
        session.commit()
        driver_id = driver.id
        gas_order_id = gas_order.id
        errant_order_id = errant_order.id
        driver_user_id = driver_user.id
        client_user_id = owner.id

    def override_get_db():
        with testing_session_local() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    token, _ = create_access_token(driver_user_id)
    with TestClient(app) as test_client:
        test_client.headers["Authorization"] = f"Bearer {token}"
        yield test_client, driver_id, gas_order_id, errant_order_id, client_user_id
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_driver_profile_and_assigned_order_lists(driver_client) -> None:
    client, driver_id, gas_order_id, errant_order_id, _ = driver_client

    profile = client.get("/drivers/me")
    assert profile.status_code == 200
    assert profile.json()["id"] == driver_id

    gas_orders = client.get("/drivers/me/gas-orders")
    errants = client.get("/drivers/me/errants")
    assert gas_orders.status_code == 200
    assert [order["id"] for order in gas_orders.json()] == [gas_order_id]
    assert errants.status_code == 200
    assert [order["id"] for order in errants.json()] == [errant_order_id]


def test_driver_can_read_assigned_client_profile(driver_client) -> None:
    client, _, _, _, client_user_id = driver_client

    response = client.get(f"/drivers/me/clients/{client_user_id}")

    assert response.status_code == 200
    assert response.json()["user_id"] == client_user_id
    assert response.json()["email"] == "owner@example.com"


def test_completed_assigned_orders_are_trips_and_weekly_earnings(driver_client) -> None:
    client, _, gas_order_id, errant_order_id, _ = driver_client
    assert client.patch(
        f"/gas-orders/{gas_order_id}",
        json={"status": "Completed"},
    ).status_code == 200
    assert client.patch(
        f"/errants/{errant_order_id}",
        json={"status": "completed"},
    ).status_code == 200

    now = datetime.now(timezone.utc)
    week_start = now.date() - timedelta(days=now.weekday())
    query = {"week_start": week_start.isoformat()}

    trips = client.get("/drivers/me/trips", params=query)
    statistics = client.get("/drivers/me/weekly-statistics", params=query)
    assert trips.status_code == 200
    assert len(trips.json()) == 2
    assert statistics.status_code == 200

    days = statistics.json()
    assert len(days) == 7
    day = days[now.weekday()]
    assert day["trip_count"] == 2
    assert day["total_earnings"] == 9000


def test_driver_cannot_edit_owner_fields_on_assigned_errant(driver_client) -> None:
    client, _, _, errant_order_id, _ = driver_client

    response = client.patch(
        f"/errants/{errant_order_id}",
        json={"status": "completed", "fee": 9999},
    )

    assert response.status_code == 403
