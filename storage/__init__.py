"""Pemilih penyimpanan klip.

Kontrak yang dijamin sama untuk semua provider:
    check_config()                              -> raise kalau belum siap
    save_clip(job_id, clip_id, path)            -> url
    open_clip(job_id, clip_id, byte_range)      -> (potongan byte, panjang, content-range)

`local` jadi default supaya project ini bisa dicoba tanpa akun Cloudflare.
"""
from pathlib import Path

from config.settings import settings

PROVIDERS = ("local", "r2")


def _impl():
    name = settings.STORAGE_PROVIDER.strip().lower()
    if name == "local":
        from storage import client_local as m
    elif name == "r2":
        from storage import client_r2 as m
    else:
        raise RuntimeError(
            f"STORAGE_PROVIDER='{settings.STORAGE_PROVIDER}' tidak dikenal. "
            f"Pilihan: {', '.join(PROVIDERS)}"
        )
    return m


def check_config() -> None:
    _impl().check_config()


def save_clip(job_id: str, clip_id: str, path: Path) -> str:
    return _impl().save_clip(job_id, clip_id, path)


def open_clip(job_id: str, clip_id: str, byte_range: str | None = None):
    return _impl().open_clip(job_id, clip_id, byte_range)


__all__ = ["PROVIDERS", "check_config", "open_clip", "save_clip"]
