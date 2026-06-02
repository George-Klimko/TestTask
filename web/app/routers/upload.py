from fastapi import APIRouter, File, Header, HTTPException, UploadFile

from app.config import settings
from app.core.validator import validate_accounts, validate_emails, validate_proxies
from app.models.upload import UploadResult
from app.services.storage import storage
from app.services.email_pool import email_pool
router = APIRouter(prefix='/upload', tags=['upload'])
MAX_BYTES = settings.max_file_size_mb * 1024 * 1024


async def read_lines(file: UploadFile) -> list[str]:
    if not (file.filename or '').lower().endswith('.txt'):
        raise HTTPException(400, 'Only .txt files are supported')
    content = await file.read()
    if len(content) > MAX_BYTES:
        raise HTTPException(400, f'File exceeds {settings.max_file_size_mb}MB')
    text = content.decode('utf-8-sig', errors='ignore')
    return [line.strip() for line in text.splitlines() if line.strip()]


def _uid(header: str | None) -> str:
    return header or 'demo-user'


@router.post('/accounts', response_model=UploadResult)
async def upload_accounts(file: UploadFile = File(...), x_user_id: str | None = Header(default=None)) -> UploadResult:
    lines = await read_lines(file)
    valid, invalid = validate_accounts(lines)
    storage.for_user(_uid(x_user_id)).accounts = valid
    return UploadResult(total=len(lines), valid=len(valid), invalid=len(invalid), preview=valid[:3])


@router.post('/proxies', response_model=UploadResult)
async def upload_proxies(file: UploadFile = File(...), x_user_id: str | None = Header(default=None)) -> UploadResult:
    lines = await read_lines(file)
    valid, invalid = validate_proxies(lines)
    storage.for_user(_uid(x_user_id)).proxies = valid
    return UploadResult(total=len(lines), valid=len(valid), invalid=len(invalid), preview=valid[:3])

@router.post('/emails', response_model=UploadResult)
async def upload_emails(
    file: UploadFile = File(...),
    x_user_id: str | None = Header(default=None)
) -> UploadResult:
    lines = await read_lines(file)
    valid, invalid = validate_emails(lines)
    storage.for_user(_uid(x_user_id)).emails = valid

    # ✅ загружаем в пул
    email_pool.load(valid)

    return UploadResult(
        total=len(lines),
        valid=len(valid),
        invalid=len(invalid),
        preview=valid[:3]
    )