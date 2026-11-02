from getpass import getpass

from sqlalchemy import select

from app.database import SessionLocal
from app.domain_models import User
from app.security import hash_password


def main() -> None:
    email = input("Administrator email: ").strip().lower()
    if not email:
        raise SystemExit("Email is required")

    with SessionLocal() as db:
        if db.scalar(select(User.id).where(User.role == "admin")) is not None:
            raise SystemExit("An administrator already exists")

        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            password = getpass("Administrator password (minimum 8 characters): ")
            if len(password) < 8:
                raise SystemExit("Password must be at least 8 characters")
            user = User(email=email, password_hash=hash_password(password))
            db.add(user)
        user.role = "admin"
        user.is_email_verified = True
        db.commit()
        print(f"Administrator ready: {user.email}")


if __name__ == "__main__":
    main()
