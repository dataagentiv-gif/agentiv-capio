"""Skema tabel jobs. Murni struktur — nol logic AI, nol keputusan bisnis."""
import uuid
from contextlib import contextmanager
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, create_engine, func, text
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
    # Bentuk tampilan dipilih PER VIDEO, bukan sekali di setelan: podcast
    # serius dan potongan lucu tidak memakai bentuk yang sama, dan orang
    # memutuskannya saat menempel link — bukan saat membuka halaman Setting.
    # Disimpan di baris job supaya klip lama tetap bisa dijelaskan bentuknya
    # walau setelan default sudah berubah sejak itu.
    layout: Mapped[str] = mapped_column(String(20), default="penuh")
    # Knob tampilan (font, ukuran, warna, jumlah kata, huruf besar) ikut
    # per video, sealasan dengan layout: begitu kontrolnya ada di halaman
    # Submit, orang mengubahnya untuk VIDEO ITU — bukan untuk semua video
    # berikutnya. Disimpan sebagai JSONB, bukan satu kolom per knob, supaya
    # menambah knob berikutnya tidak menuntut ALTER TABLE lagi.
    gaya: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=Status.QUEUED, index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    clips: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # Slot worker yang sedang/terakhir mengerjakan job ini (mis. "slot-0").
    # Dipakai bereskan_gantung() supaya worker yang baru menyala di mode multi
    # cuma membereskan job miliknya sendiri, bukan job worker lain yang masih
    # sehat. Bukan untuk ditampilkan — tidak masuk as_dict().
    worker_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def as_dict(self) -> dict:
        from pipeline.templates import TEMPLATES

        return {
            "id": str(self.id),
            "url": self.url,
            "target_clips": self.target_clips,
            "layout": self.layout,
            "gaya": self.gaya or {},
            "template_id": self.layout if self.layout in TEMPLATES else None,
            "adjustments": self.gaya or {},
            "retryable": self.status == Status.FAILED and self.layout in TEMPLATES,
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

    # create_all TIDAK menambah kolom ke tabel yang sudah ada — ia hanya
    # membuat tabel yang belum ada sama sekali. Tanpa baris di bawah, database
    # yang sudah terlanjur jalan akan menolak setiap INSERT dengan
    # UndefinedColumn, dan itu terlihat seperti kode yang rusak padahal cuma
    # skemanya yang tertinggal.
    #
    # Project ini sengaja belum memakai tool migrasi (PRD Bagian 7), jadi
    # penambahan kolom ditulis di sini secara idempoten. Kalau nanti kolomnya
    # bertambah banyak, ini saatnya beralih ke Alembic.
    #
    # ponytail: satu ALTER per kolom baru. Layak diganti tool migrasi begitu
    # ada perubahan yang butuh mengisi ulang data lama, bukan sekadar menambah
    # kolom berdefault.
    with engine.begin() as c:
        for kolom in (
            "layout VARCHAR(20) NOT NULL DEFAULT 'penuh'",
            "gaya JSONB",
            "worker_id VARCHAR(64)",
        ):
            c.execute(text(f"ALTER TABLE jobs ADD COLUMN IF NOT EXISTS {kolom}"))
