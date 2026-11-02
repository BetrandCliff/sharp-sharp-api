from fastapi import APIRouter, Depends

from app.auth_routes import get_current_user
from app.domain_models import User
from app.domain_schemas import UploadRequest, UploadResponse
from app.storage_service import create_audio_upload

router = APIRouter(prefix="/storage", tags=["storage"])


@router.post("/audio/upload-url", response_model=UploadResponse)
def create_audio_upload_url(
    request: UploadRequest,
    user: User = Depends(get_current_user),
) -> UploadResponse:
    upload_url, public_url, object_key, expires_in = create_audio_upload(
        user.id,
        request.filename,
        request.content_type,
        request.content_length,
    )
    return UploadResponse(
        upload_url=upload_url,
        public_url=public_url,
        object_key=object_key,
        expires_in=expires_in,
        content_type=request.content_type,
        content_length=request.content_length,
    )
