from datetime import datetime

from pydantic import AliasChoices, BaseModel, ConfigDict, EmailStr, Field


class Credentials(BaseModel):
    email: EmailStr
    # The Flutter signup form currently accepts passwords from 6 characters.
    # Keep login and registration aligned with the client contract.
    password: str = Field(min_length=6, max_length=128)


class RegistrationRequest(Credentials):
    user_name: str | None = Field(
        default=None,
        validation_alias=AliasChoices("userName", "fullNames", "name", "user_name"),
        max_length=160,
    )
    phone: str | None = Field(default=None, max_length=40)


class EmailRequest(BaseModel):
    email: EmailStr


class VerifyEmailRequest(EmailRequest):
    code: str = Field(pattern=r"^[0-9]{6}$")


class PasswordResetRequest(VerifyEmailRequest):
    new_password: str = Field(min_length=8, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=32)


class ProfileUpdate(BaseModel):
    user_name: str = Field(alias="userName", min_length=1, max_length=160)
    phone: str | None = Field(default=None, max_length=40)
    model_config = ConfigDict(populate_by_name=True)


class ProfileResponse(BaseModel):
    user_id: str
    user_name: str = Field(alias="userName")
    email: EmailStr
    phone: str | None = None
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class UserResponse(BaseModel):
    id: str
    email: EmailStr
    is_email_verified: bool
    role: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_at: datetime
