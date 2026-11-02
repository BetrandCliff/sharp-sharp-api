from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth_schemas import (
    Credentials,
    EmailRequest,
    PasswordResetRequest,
    ProfileResponse,
    ProfileUpdate,
    RegistrationRequest,
    RefreshRequest,
    TokenResponse,
    UserResponse,
    VerifyEmailRequest,
)
from app.database import get_db
from app.domain_models import AuthSession, EmailVerification, Profile, User
from app.email_service import send_email_code
from app.security import (
    ACCESS_TOKEN_MINUTES,
    REFRESH_TOKEN_DAYS,
    create_access_token,
    hash_email_code,
    hash_password,
    hash_refresh_token,
    decode_access_token,
    new_email_code,
    new_refresh_token,
    verify_email_code,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["authentication"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")
CODE_LIFETIME = timedelta(minutes=15)
MAX_CODE_ATTEMPTS = 5


def _issue_tokens(user: User, db: Session) -> TokenResponse:
    access_token, access_expires_at = create_access_token(user.id)
    refresh_token = new_refresh_token()
    db.add(
        AuthSession(
            user_id=user.id,
            refresh_token_hash=hash_refresh_token(refresh_token),
            expires_at=datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_DAYS),
        )
    )
    db.commit()
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=access_expires_at,
    )


def _save_email_code(user: User, purpose: str, db: Session) -> str:
    code = new_email_code()
    verification = db.scalar(
        select(EmailVerification).where(
            EmailVerification.user_id == user.id,
            EmailVerification.purpose == purpose,
        )
    )
    values = {
        "code_hash": hash_email_code(code),
        "expires_at": datetime.now(timezone.utc) + CODE_LIFETIME,
        "attempts": 0,
    }
    if verification is None:
        db.add(EmailVerification(user_id=user.id, purpose=purpose, **values))
    else:
        for field, value in values.items():
            setattr(verification, field, value)
    db.flush()
    return code


def _verify_code(user: User, purpose: str, code: str, db: Session) -> EmailVerification:
    verification = db.scalar(
        select(EmailVerification).where(
            EmailVerification.user_id == user.id,
            EmailVerification.purpose == purpose,
        )
    )
    if verification is None:
        raise HTTPException(status_code=400, detail="Invalid or expired code")
    expires_at = verification.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc) or verification.attempts >= MAX_CODE_ATTEMPTS:
        db.delete(verification)
        db.commit()
        raise HTTPException(status_code=400, detail="Invalid or expired code")
    if not verify_email_code(code, verification.code_hash):
        verification.attempts += 1
        db.commit()
        raise HTTPException(status_code=400, detail="Invalid or expired code")
    return verification


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(request: RegistrationRequest, db: Session = Depends(get_db)) -> dict[str, str]:
    email = str(request.email).lower()
    if db.scalar(select(User).where(User.email == email)) is not None:
        raise HTTPException(status_code=409, detail="An account with this email already exists")

    user = User(email=email, password_hash=hash_password(request.password))
    db.add(user)
    db.flush()
    if request.user_name is not None or request.phone is not None:
        db.add(
            Profile(
                user_id=user.id,
                email=email,
                user_name=request.user_name or "",
                phone=request.phone,
            )
        )
    code = _save_email_code(user, "signup", db)
    try:
        send_email_code(email, code, "signup")
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"detail": "Verification code sent"}


@router.post("/verify-email", response_model=TokenResponse)
def verify_email(request: VerifyEmailRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.scalar(select(User).where(User.email == str(request.email).lower()))
    if user is None:
        raise HTTPException(status_code=400, detail="Invalid or expired code")
    verification = _verify_code(user, "signup", request.code, db)
    user.is_email_verified = True
    db.delete(verification)
    db.commit()
    return _issue_tokens(user, db)


@router.post("/resend-verification")
def resend_verification(request: EmailRequest, db: Session = Depends(get_db)) -> dict[str, str]:
    user = db.scalar(select(User).where(User.email == str(request.email).lower()))
    if user is not None and not user.is_email_verified:
        code = _save_email_code(user, "signup", db)
        try:
            send_email_code(user.email, code, "signup")
            db.commit()
        except Exception:
            db.rollback()
            raise
    return {"detail": "If the account needs verification, a code has been sent"}


@router.post("/login", response_model=TokenResponse)
def login(request: Credentials, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.scalar(select(User).where(User.email == str(request.email).lower()))
    if user is None or not verify_password(request.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.is_email_verified:
        raise HTTPException(status_code=403, detail="Email verification required")
    return _issue_tokens(user, db)


@router.post("/refresh", response_model=TokenResponse)
def refresh_tokens(request: RefreshRequest, db: Session = Depends(get_db)) -> TokenResponse:
    token_hash = hash_refresh_token(request.refresh_token)
    session = db.scalar(
        select(AuthSession).where(AuthSession.refresh_token_hash == token_hash)
    )
    now = datetime.now(timezone.utc)
    if session is None or session.revoked_at is not None:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    expires_at = session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= now:
        session.revoked_at = now
        db.commit()
        raise HTTPException(status_code=401, detail="Refresh token expired")

    user = db.get(User, session.user_id)
    if user is None or not user.is_email_verified:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    session.revoked_at = now
    return _issue_tokens(user, db)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: RefreshRequest,
    db: Session = Depends(get_db),
) -> None:
    session = db.scalar(
        select(AuthSession).where(
            AuthSession.refresh_token_hash == hash_refresh_token(request.refresh_token)
        )
    )
    if session is not None and session.revoked_at is None:
        session.revoked_at = datetime.now(timezone.utc)
        db.commit()


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    try:
        payload = decode_access_token(token)
        user_id = str(payload["sub"])
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid access token") from exc

    user = db.get(User, user_id)
    if user is None or not user.is_email_verified:
        raise HTTPException(status_code=401, detail="Account is not available")
    return user


@router.get("/me", response_model=UserResponse)
def get_me(user: User = Depends(get_current_user)) -> User:
    return user


@router.get("/profile", response_model=ProfileResponse)
def get_profile(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Profile:
    profile = db.get(Profile, user.id)
    if profile is None:
        # A verified account may not have completed the profile step yet.
        # Return the same shape as an existing profile without creating a row.
        return Profile(user_id=user.id, email=user.email, user_name="")
    return profile


@router.put("/profile", response_model=ProfileResponse)
def update_profile(
    request: ProfileUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Profile:
    profile = db.get(Profile, user.id)
    if profile is None:
        profile = Profile(user_id=user.id, email=user.email, user_name=request.user_name)
        db.add(profile)
    profile.user_name = request.user_name
    profile.email = user.email
    if "phone" in request.model_fields_set:
        profile.phone = request.phone
    db.commit()
    db.refresh(profile)
    return profile


@router.post("/request-password-reset")
def request_password_reset(request: EmailRequest, db: Session = Depends(get_db)) -> dict[str, str]:
    user = db.scalar(select(User).where(User.email == str(request.email).lower()))
    if user is not None and user.is_email_verified:
        code = _save_email_code(user, "password_reset", db)
        try:
            send_email_code(user.email, code, "password_reset")
            db.commit()
        except Exception:
            db.rollback()
            raise
    return {"detail": "If the account exists, a reset code has been sent"}


@router.post("/reset-password")
def reset_password(
    request: PasswordResetRequest,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    user = db.scalar(select(User).where(User.email == str(request.email).lower()))
    if user is None:
        raise HTTPException(status_code=400, detail="Invalid or expired code")
    verification = _verify_code(user, "password_reset", request.code, db)
    user.password_hash = hash_password(request.new_password)
    db.delete(verification)
    for session in db.scalars(
        select(AuthSession).where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
    ):
        session.revoked_at = datetime.now(timezone.utc)
    db.commit()
    return {"detail": "Password reset successfully"}
