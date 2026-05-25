from enum import Enum
from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    pending = 'pending'
    running = 'running'
    paused = 'paused'
    stopped = 'stopped'
    done = 'done'
    error = 'error'


class JobConfig(BaseModel):
    threads: int = Field(default=20, ge=1, le=50)
    timeout: int = Field(default=30, ge=5, le=300)
    headless: bool = True


class JobStartRequest(BaseModel):
    config: JobConfig = JobConfig()


class JobInfo(BaseModel):
    job_id: str
    status: JobStatus
    total: int
    done: int = 0
    success: int = 0
    error: int = 0
    progress_pct: int = 0