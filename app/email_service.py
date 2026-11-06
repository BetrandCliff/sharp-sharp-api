# import os
# import smtplib
# import ssl
# from email.message import EmailMessage

# from fastapi import HTTPException


# def _setting(*names: str) -> str | None:
#     for name in names:
#         value = os.getenv(name)
#         if value:
#             return value
#     return None


# def send_email_code(email: str, code: str, purpose: str) -> None:
#     host = _setting("SMTP_HOST", "smtp_host")
#     username = _setting("SMTP_USER", "smtp_user")
#     password = _setting("SMTP_PASSWORD", "SMTP_PASS", "smtp_pass")
#     sender = _setting("SMTP_SENDER_EMAIL", "SMTP_ADMIN_EMAIL", "smtp_admin_email")
#     port = int(_setting("SMTP_PORT", "smtp_port") or "587")
#     if not all((host, username, password, sender)):
#         raise HTTPException(status_code=503, detail="Email service is not configured")

#     action = "verify your email" if purpose == "signup" else "reset your password"
#     message = EmailMessage()
#     message["Subject"] = "Sharp-Sharp verification code"
#     message["From"] = sender
#     message["To"] = email
#     message.set_content(
#         f"Use this code to {action}: {code}\n\n"
#         "The code expires in 15 minutes. If you did not request it, ignore this message."
#     )

#     try:
#         context = ssl.create_default_context()
#         if port == 465:
#             with smtplib.SMTP_SSL(host, port, context=context, timeout=15) as server:
#                 server.login(username, password)
#                 server.send_message(message)
#         else:
#             with smtplib.SMTP(host, port, timeout=15) as server:
#                 server.starttls(context=context)
#                 server.login(username, password)
#                 server.send_message(message)
#     except (OSError, smtplib.SMTPException) as exc:
#         raise HTTPException(status_code=502, detail="Could not send verification email") from exc


import os
import httpx

from fastapi import HTTPException


def _setting(name: str) -> str | None:
    value = os.getenv(name)
    return value.strip() if value else None


def send_email_code(email: str, code: str, purpose: str) -> None:
    api_key = _setting("RESEND_API_KEY")
    sender = _setting("RESEND_FROM_EMAIL")

    if not api_key or not sender:
        raise HTTPException(
            status_code=503,
            detail="Email service is not configured",
        )

    action = (
        "verify your email"
        if purpose == "signup"
        else "reset your password"
    )

    payload = {
        "from": sender,
        "to": [email],
        "subject": "Sharp-Sharp verification code",
        "text": (
            f"Use this code to {action}: {code}\n\n"
            "The code expires in 15 minutes. "
            "If you did not request it, ignore this message."
        ),
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        response = httpx.post(
            "https://api.resend.com/emails",
            json=payload,
            headers=headers,
            timeout=20.0,
        )
        response.raise_for_status()

    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail="Email provider rejected the verification email",
        ) from exc

    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502,
            detail="Could not connect to the email provider",
        ) from exc