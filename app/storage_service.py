import os
import re
from pathlib import PurePath
from uuid import uuid4

import boto3
from botocore.config import Config
from fastapi import HTTPException


def create_audio_upload(
    user_id: str,
    filename: str,
    content_type: str,
    content_length: int,
) -> tuple[str, str, str, int]:
    max_upload_bytes = int(os.getenv("MAX_UPLOAD_MB", "50")) * 1024 * 1024
    if content_length > max_upload_bytes:
        raise HTTPException(status_code=413, detail="Audio file exceeds the upload limit")

    account_id = os.getenv("R2_ACCOUNT_ID")
    endpoint = os.getenv("R2_ENDPOINT")
    access_key = os.getenv("R2_ACCESS_KEY_ID")
    secret_key = os.getenv("R2_SECRET_ACCESS_KEY")
    bucket = os.getenv("R2_BUCKET")
    public_url = os.getenv("R2_PUBLIC_URL", "").rstrip("/")
    if not all((account_id, access_key, secret_key, bucket, public_url)):
        raise HTTPException(status_code=503, detail="Audio storage is not configured")

    endpoint = endpoint or f"https://{account_id}.r2.cloudflarestorage.com"
    suffix = PurePath(filename).suffix.lower()
    suffix = suffix if re.fullmatch(r"\.[a-z0-9]{1,8}", suffix) else ".audio"
    object_key = f"chat-audio/{user_id}/{uuid4().hex}{suffix}"
    expires_in = 300

    try:
        client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name="auto",
            config=Config(signature_version="s3v4"),
        )
        upload_url = client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": bucket,
                "Key": object_key,
                "ContentType": content_type,
                "ContentLength": content_length,
            },
            ExpiresIn=expires_in,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Could not prepare audio upload") from exc

    return upload_url, f"{public_url}/{object_key}", object_key, expires_in
