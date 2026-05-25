from fastapi import APIRouter, Header, HTTPException

from app.config import settings
from app.models.job import JobInfo, JobStartRequest
from app.services.job_manager import job_manager
from app.services.storage import storage

router = APIRouter(prefix='/jobs', tags=['jobs'])


def _uid(header: str | None) -> str:
    return header or 'demo-user'


def _ensure_owner(job_id: str, user_id: str) -> None:
    """
    Keep compatibility with both job_manager variants:
    - with owned_by(job_id, user_id)
    - without ownership checks
    """
    if hasattr(job_manager, 'owned_by') and callable(getattr(job_manager, 'owned_by')):
        if not job_manager.owned_by(job_id, user_id):
            raise HTTPException(404, 'Job not found')


@router.post('/start')
async def start_job(req: JobStartRequest, x_user_id: str | None = Header(default=None)) -> dict:
    user_id = _uid(x_user_id)
    data = storage.for_user(user_id)

    if not data.accounts:
        raise HTTPException(400, 'Upload accounts first')

    if req.config.threads > settings.max_threads_per_job:
        raise HTTPException(400, f'threads > {settings.max_threads_per_job}')

    # IMPORTANT: use keyword args to avoid argument order bugs.
    job_id = await job_manager.start(
        accounts=data.accounts,
        proxies=data.proxies,
        threads=req.config.threads,
        headless=req.config.headless,
        timeout_sec=req.config.timeout,
    )
    return {'job_id': job_id}


@router.get('/{job_id}', response_model=JobInfo)
async def get_status(job_id: str, x_user_id: str | None = Header(default=None)) -> JobInfo:
    _ensure_owner(job_id, _uid(x_user_id))

    job = job_manager.get(job_id)
    if not job:
        raise HTTPException(404, 'Job not found')
    return job


@router.post('/{job_id}/pause')
async def pause(job_id: str, x_user_id: str | None = Header(default=None)) -> dict:
    _ensure_owner(job_id, _uid(x_user_id))

    if not job_manager.get(job_id):
        raise HTTPException(404, 'Job not found')

    await job_manager.pause(job_id)
    return {'ok': True}


@router.post('/{job_id}/resume')
async def resume(job_id: str, x_user_id: str | None = Header(default=None)) -> dict:
    _ensure_owner(job_id, _uid(x_user_id))

    if not job_manager.get(job_id):
        raise HTTPException(404, 'Job not found')

    await job_manager.resume(job_id)
    return {'ok': True}


@router.post('/{job_id}/stop')
async def stop(job_id: str, x_user_id: str | None = Header(default=None)) -> dict:
    _ensure_owner(job_id, _uid(x_user_id))

    if not job_manager.get(job_id):
        raise HTTPException(404, 'Job not found')

    await job_manager.stop(job_id)
    return {'ok': True}