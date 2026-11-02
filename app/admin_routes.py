from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.admin_schemas import CompanyCreate, DriverCreate
from app.auth_routes import get_current_user
from app.database import get_db
from app.domain_models import Company, Driver, User
from app.domain_schemas import CompanyResponse, DriverResponse

router = APIRouter(prefix="/admin", tags=["administration"])


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Administrator access required")
    return user


@router.post("/companies", response_model=CompanyResponse, status_code=status.HTTP_201_CREATED)
def create_company(
    request: CompanyCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> Company:
    if request.auth_user_id is not None and db.get(User, request.auth_user_id) is None:
        raise HTTPException(status_code=404, detail="Company account not found")
    company = Company(
        auth_id=request.auth_user_id,
        company_name=request.company_name,
        role=request.role,
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


@router.get("/companies", response_model=list[CompanyResponse])
def list_companies(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> list[Company]:
    return list(db.scalars(select(Company).order_by(Company.company_name)).all())


@router.post("/drivers", response_model=DriverResponse, status_code=status.HTTP_201_CREATED)
def create_driver(
    request: DriverCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> Driver:
    if db.get(Company, request.company_id) is None:
        raise HTTPException(status_code=404, detail="Company not found")
    if request.auth_id is not None and db.get(User, request.auth_id) is None:
        raise HTTPException(status_code=404, detail="Driver account not found")
    if request.auth_id and db.scalar(select(Driver.id).where(Driver.auth_id == request.auth_id)):
        raise HTTPException(status_code=409, detail="Account already belongs to a driver")
    driver = Driver(
        auth_id=request.auth_id,
        company_id=request.company_id,
        name=request.name,
        phone=request.phone,
        email=str(request.email or ""),
    )
    if request.auth_id is not None:
        account = db.get(User, request.auth_id)
        account.role = "driver"
    db.add(driver)
    db.commit()
    db.refresh(driver)
    return driver


@router.get("/drivers", response_model=list[DriverResponse])
def list_drivers(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> list[Driver]:
    return list(db.scalars(select(Driver).order_by(Driver.name)).all())


@router.patch("/users/{user_id}/role")
def update_user_role(
    user_id: str,
    role: str,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict[str, str]:
    if role not in {"client", "driver", "company", "admin"}:
        raise HTTPException(status_code=422, detail="Unsupported role")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    user.role = role
    db.commit()
    return {"user_id": user.id, "role": user.role}
