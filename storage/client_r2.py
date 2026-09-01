"""Adapter Cloudflare R2. R2 itu S3-compatible, jadi boto3 apa adanya cukup."""
from functools import lru_cache
from pathlib import Path

import boto3
from botocore.config import Config

from config.settings import settings


REQUIRED = (
    "R2_ACCOUNT_ID",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "R2_BUCKET",
    "R2_PUBLIC_BASE_URL",
)


def check_config() -> None:
    """Pastikan konfigurasi R2 lengkap. Dipanggil saat worker start.

    Upload adalah langkah TERAKHIR pipeline, jadi tanpa pemeriksaan di depan
    satu env var yang kosong baru ketahuan setelah download, transkrip, dan
    render selesai — belasan menit terbuang untuk job yang sejak awal pasti
    gagal. Lebih buruk lagi, pesannya muncul sebagai ValueError dari dalam
    botocore ("Invalid endpoint: https://.r2.cloudflarestorage.com") yang tidak
    menyebut env var mana yang bolong.
    """
    kosong = [k for k in REQUIRED if not getattr(settings, k, "")]
    if kosong:
        raise RuntimeError(
            "Konfigurasi R2 belum lengkap, isi di .env: " + ", ".join(kosong)
        )


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


def open_clip(job_id: str, clip_id: str, byte_range: str | None = None):
    """(potongan byte, panjang, Content-Range) — bentuk yang sama dengan lokal.

    Diambil lewat endpoint S3 (*.r2.cloudflarestorage.com), BUKAN domain publik
    r2.dev — banyak ISP Indonesia memblokir r2.dev di level DNS, sementara
    endpoint S3 tidak kena. Detail boto3 ditahan di sini supaya api/ tidak perlu
    tahu soal S3.
    """
    kw = {"Bucket": settings.R2_BUCKET, "Key": f"{job_id}/clips/{clip_id}.mp4"}
    if byte_range:
        kw["Range"] = byte_range
    obj = _client().get_object(**kw)
    return obj["Body"].iter_chunks(chunk_size=256 * 1024), obj["ContentLength"], obj.get("ContentRange")


def save_clip(job_id: str, clip_id: str, path: Path) -> str:
    """Upload satu klip, kembalikan URL publiknya."""
    key = f"{job_id}/clips/{clip_id}.mp4"
    _client().upload_file(
        str(path),
        settings.R2_BUCKET,
        key,
        ExtraArgs={"ContentType": "video/mp4"},
    )
    return f"{settings.R2_PUBLIC_BASE_URL.rstrip('/')}/{key}"
