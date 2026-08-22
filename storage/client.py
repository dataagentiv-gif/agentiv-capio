"""Adapter Cloudflare R2. R2 itu S3-compatible, jadi boto3 apa adanya cukup."""
from functools import lru_cache
from pathlib import Path

import boto3
from botocore.config import Config

from config.settings import settings


@lru_cache(maxsize=1)
def _client():
    # region_name="auto" wajib untuk R2 — dia tidak punya region ala AWS, tapi
    # SigV4 tetap menuntut sebuah nilai region saat menandatangani request.
    return boto3.client(
        "s3",
        endpoint_url=settings.r2_endpoint,
        aws_access_key_id=settings.R2_ACCESS_KEY_ID,
        aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        region_name="auto",
        config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
    )


def upload_clip(job_id: str, clip_id: str, path: Path) -> str:
    """Upload satu klip, kembalikan URL publiknya."""
    key = f"{job_id}/clips/{clip_id}.mp4"
    _client().upload_file(
        str(path),
        settings.R2_BUCKET,
        key,
        ExtraArgs={"ContentType": "video/mp4"},
    )
    return f"{settings.R2_PUBLIC_BASE_URL.rstrip('/')}/{key}"
