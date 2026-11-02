from pydantic import BaseModel, EmailStr, Field


class CompanyCreate(BaseModel):
    company_name: str = Field(min_length=1, max_length=200)
    role: str = Field(default="supplier", pattern="^(supplier|admin)$")
    auth_user_id: str | None = None


class DriverCreate(BaseModel):
    auth_id: str | None = None
    company_id: str
    name: str = Field(min_length=1, max_length=160)
    phone: str = Field(max_length=40)
    email: EmailStr | None = None
