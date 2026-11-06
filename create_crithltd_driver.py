
from getpass import getpass

from sqlalchemy import func, select

from app import models  # Ensure all models are registered
from app.database import SessionLocal
from app.domain_models import (
    Company,
    Driver,
    Profile,
    User,
)
from app.security import hash_password


# ==========================================
# COMPANY DETAILS
# ==========================================

COMPANY_NAME = "Sharp-Sharp"
AUTHORIZATION_ID = "SS-729733"


# ==========================================
# DRIVER DETAILS
# ==========================================

DRIVER_NAME = "Hakeem Smith"
DRIVER_EMAIL = "crithltd@gmail.com"
DRIVER_PHONE = "+237 672973390"


def create_records():
    password = getpass("Enter a NEW driver password: ")
    confirm_password = getpass("Confirm driver password: ")

    if password != confirm_password:
        print("ERROR: Passwords do not match.")
        return

    if len(password) < 8:
        print("ERROR: Password must contain at least 8 characters.")
        return

    session = SessionLocal()

    try:
        # ------------------------------------------
        # 1. CHECK EXISTING USER
        # ------------------------------------------

        existing_user = session.scalar(
            select(User).where(
                func.lower(User.email) == DRIVER_EMAIL.lower()
            )
        )

        if existing_user:
            print("ERROR: A user with this email already exists.")
            print("No records were changed.")
            return

        # ------------------------------------------
        # 2. CHECK EXISTING DRIVER
        # ------------------------------------------

        existing_driver = session.scalar(
            select(Driver).where(
                func.lower(Driver.email) == DRIVER_EMAIL.lower()
            )
        )

        if existing_driver:
            print("ERROR: A driver with this email already exists.")
            print("No records were changed.")
            return

        # ------------------------------------------
        # 3. CHECK COMPANY
        # ------------------------------------------

        company_by_auth = session.scalar(
            select(Company).where(
                Company.authorization_id == AUTHORIZATION_ID
            )
        )

        company_by_name = session.scalar(
            select(Company).where(
                func.lower(Company.company_name) == COMPANY_NAME.lower()
            )
        )

        if company_by_auth and (
            company_by_auth.company_name.casefold()
            != COMPANY_NAME.casefold()
        ):
            print(
                "ERROR: This authorization ID belongs to another company."
            )
            return

        if company_by_name and (
            company_by_name.authorization_id != AUTHORIZATION_ID
        ):
            print(
                "ERROR: This company name already exists "
                "with a different authorization ID."
            )
            return

        if (
            company_by_auth
            and company_by_name
            and company_by_auth.id != company_by_name.id
        ):
            print("ERROR: Conflicting company records found.")
            return

        # Reuse an existing matching company or create one.
        company = company_by_auth or company_by_name

        if company is None:
            company = Company(
                company_name=COMPANY_NAME,
                authorization_id=AUTHORIZATION_ID,
                role="supplier",
                auth_id=None,
            )

            session.add(company)
            session.flush()

            print("Company created successfully.")

        else:
            print("Existing matching company found. Reusing it.")

        # ------------------------------------------
        # 4. CREATE DRIVER USER ACCOUNT
        # ------------------------------------------

        user = User(
            email=DRIVER_EMAIL.lower(),
            password_hash=hash_password(password),
            role="driver",
            is_email_verified=True,
        )

        session.add(user)
        session.flush()

        # ------------------------------------------
        # 5. CREATE DRIVER PROFILE
        # ------------------------------------------

        profile = Profile(
            user_id=user.id,
            user_name=DRIVER_NAME,
            email=DRIVER_EMAIL.lower(),
            phone=DRIVER_PHONE,
        )

        session.add(profile)

        # ------------------------------------------
        # 6. CREATE DRIVER RECORD
        # ------------------------------------------

        driver = Driver(
            auth_id=user.id,
            company_id=company.id,
            name=DRIVER_NAME,
            phone=DRIVER_PHONE,
            email=DRIVER_EMAIL.lower(),
        )

        session.add(driver)

        # ------------------------------------------
        # 7. SAVE EVERYTHING
        # ------------------------------------------

        session.commit()

        print("\nSUCCESS: Company and driver created.")
        print("-----------------------------------------")
        print(f"Company name: {company.company_name}")
        print(f"Authorization ID: {company.authorization_id}")
        print(f"Company ID: {company.id}")
        print("-----------------------------------------")
        print(f"Driver name: {driver.name}")
        print(f"Driver email: {driver.email}")
        print(f"Driver phone: {driver.phone}")
        print(f"Driver user ID: {user.id}")
        print(f"Driver company ID: {driver.company_id}")
        print("-----------------------------------------")
        print("User role: driver")
        print("Email verification: AUTOMATICALLY VERIFIED")
        print("OTP required: NO")
        print("Account status: READY FOR LOGIN")
        print("-----------------------------------------")

    except Exception as exc:
        session.rollback()
        print(f"\nERROR: {exc}")
        print("Database transaction rolled back.")

    finally:
        session.close()


if __name__ == "__main__":
    create_records()
