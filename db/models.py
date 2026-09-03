"""Skema tabel jobs. Murni struktur — nol logic AI, nol keputusan bisnis."""
import uuid
from contextlib import contextmanager
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, create_engine, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from config.settings import settings


class Status:
    """State machine job (PRD Bagian 5).

    Disimpan sebagai VARCHAR, bukan enum native Postgres: build ini masih akan
    kedatangan stage baru (context-research), dan tiap nilai baru pada enum
    native menuntut ALTER TYPE sementara project ini belum pakai tool migrasi.

    METADATA dan UPLOADING tidak ada di daftar PRD. Ditambahkan karena keduanya
    memakan waktu nyata; tanpa itu history.html menampilkan "rendering" padahal
    render sudah selesai.
    """

    QUEUED = "queued"
    DOWNLOADING = "downloading"
    TRANSCRIBING = "transcribing"
    SEGMENTING = "segmenting"
    REFINING = "refining"
    CAPTIONING = "captioning"
    CROPPING = "cropping"
    RENDERING = "rendering"
    METADATA = "metadata"
    UPLOADING = "uploading"
    DONE = "done"
    FAILED = "failed"

    #: Status yang berarti "ada worker yang sedang mengerjakannya sekarang".
    #: QUEUED sengaja TIDAK termasuk — job itu belum disentuh siapa pun dan
    #: masih sah dikerjakan setelah worker menyala lagi.
    BERJALAN = (
        DOWNLOADING, TRANSCRIBING, SEGMENTING, REFINING,
        CAPTIONING, CROPPING, RENDERING, METADATA, UPLOADING,
    )


class Base(DeclarativeBase):
    pass


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    url: Mapped[str] = mapped_column(Text)
    target_clips: Mapped[int] = mapped_column(Integer, default=8)
    status: Mapped[str] = mapped_column(String(20), default=Status.QUEUED, index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    clips: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def as_dict(self) -> dict:
        return {
            "id": str(self.id),
            "url": self.url,
            "target_clips": self.target_clips,
            "status": self.status,
            "progress": self.progress,
            "error": self.error,
            "clips": self.clips or [],
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# pool_pre_ping: worker bisa idle berjam-jam antar job, dan Postgres di container
# memutus koneksi menganggur. Tanpa ini job pertama setelah idle gagal.
engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def session_scope():
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def init() -> None:
    """Bikin tabel kalau belum ada. Dipanggil saat startup API."""
    Base.metadata.create_all(engine)
