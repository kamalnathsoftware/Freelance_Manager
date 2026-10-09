"""File storage on local disk. Replace with S3/R2 by keeping the same two functions."""

import os
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile

from app.core.config import get_settings

ALLOWED_PREFIXES = (
    "image/",
    "text/",
    "application/pdf",
    "application/zip",
    "application/msword",
    "application/vnd.openxmlformats-officedocument",
    "application/vnd.ms-excel",
)


async def save_upload(file: UploadFile) -> tuple[str, int, str]:
    """Returns (stored_path, size, content_type). Enforces size and type limits."""
    s = get_settings()
    ctype = file.content_type or "application/octet-stream"
    if not ctype.startswith(ALLOWED_PREFIXES):
        raise HTTPException(415, f"File type {ctype} is not allowed")
    limit = s.max_upload_mb * 1024 * 1024
    root = Path(s.upload_dir)
    root.mkdir(parents=True, exist_ok=True)
    name = uuid.uuid4().hex  # never use the client filename on disk
    path = root / name
    size = 0
    try:
        with path.open("wb") as out:
            while chunk := await file.read(64 * 1024):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, f"File exceeds {s.max_upload_mb} MB")
                out.write(chunk)
    except HTTPException:
        path.unlink(missing_ok=True)
        raise
    return str(path), size, ctype


def delete_file(path: str) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
