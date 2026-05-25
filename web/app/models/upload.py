from pydantic import BaseModel


class UploadResult(BaseModel):
    total: int
    valid: int
    invalid: int
    preview: list[str]