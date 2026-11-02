import os
import smtplib
import ssl
from email.message import EmailMessage

from fastapi import HTTPException


def _setting(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None


def send_email_code(email: str, code: str, purpose: str) -> None:
    host = _setting("SMTP_HOST", "smtp_host")
    username = _setting("SMTP_USER", "smtp_user")
    password = _setting("SMTP_PASSWORD", "SMTP_PASS", "smtp_pass")
    sender = _setting("SMTP_SENDER_EMAIL", "SMTP_ADMIN_EMAIL", "smtp_admin_email")
    port = int(_setting("SMTP_PORT", "smtp_port") or "587")
    if not all((host, username, password, sender)):
        raise HTTPException(status_code=503, detail="Email service is not configured")

    action = "verify your email" if purpose == "signup" else "reset your password"
    message = EmailMessage()
    message["Subject"] = "Sharp-Sharp verification code"
    message["From"] = sender
    message["To"] = email
    message.set_content(
        f"Use this code to {action}: {code}\n\n"
        "The code expires in 15 minutes. If you did not request it, ignore this message."
    )

    try:
        context = ssl.create_default_context()
        if port == 465:
            with smtplib.SMTP_SSL(host, port, context=context, timeout=15) as server:
                server.login(username, password)
                server.send_message(message)
        else:
            with smtplib.SMTP(host, port, timeout=15) as server:
                server.starttls(context=context)
                server.login(username, password)
                server.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        raise HTTPException(status_code=502, detail="Could not send verification email") from exc
