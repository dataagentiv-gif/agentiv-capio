from pydantic import BaseModel, Field, field_validator, model_validator

from config.settings import settings


class JobCreate(BaseModel):
    url: str
    target_clips: int = Field(default=settings.TARGET_CLIPS_DEFAULT, ge=1, le=20)
    # Bentuk tampilan dipilih di sini, bukan di halaman Setting: tiap video
    # bisa menuntut bentuk yang berbeda, dan keputusannya diambil saat menempel
    # link. Kosong = ikut default yang dipilih di Setting.
    layout: str | None = None
    # Knob tampilan untuk video INI. Kosong = ikut default di halaman Setting.
    gaya: dict | None = None

    @field_validator("gaya")
    @classmethod
    def _gaya_bersih(cls, v):
        """Batas kepercayaan: isinya masuk ke generator .ass dan ikut tersimpan
        di database. Hanya kunci yang dikenal yang lolos — sisanya dibuang
        diam-diam, bukan ditolak, supaya form versi lama tetap bisa submit."""
        if not v:
            return None
        from pipeline.stages.caption import GAYA_AKTIF

        BOLEH = {"font", "ukuran", "aktif", "kata", "upper",
                 "active_word_background_color", "active_word_text_color"}
        bersih = {k: v[k] for k in BOLEH if v.get(k) not in (None, "", 0, "0")}
        if v.get("active_word_style") in GAYA_AKTIF:
            bersih["active_word_style"] = v["active_word_style"]
        # Angka yang NOL-nya bermakna — bayangan 0% berarti tanpa bayangan,
        # radius 0 berarti sudut siku — bukan "ikut default", jadi tidak boleh
        # lewat saringan di atas. Dipaksa jadi int sekalian: nilainya masuk ke
        # rumus ffmpeg dan path gambar .ass. Rentangnya dijepit di tempat
        # pemakaiannya, bukan di sini.
        for k in ("redup_luas", "redup_gelap", "active_word_border_radius",
                  "active_word_padding_x", "active_word_padding_y"):
            try:
                bersih[k] = int(float(v[k]))
            except (KeyError, TypeError, ValueError, OverflowError):
                pass
        # `caption` disaring terpisah, dan itu bukan gaya-gayaan: ia satu-satunya
        # knob yang nilai bermaknanya False, sementara `False == 0` di Python
        # membuat saringan di atas MEMBUANGNYA justru saat caption dimatikan.
        # Hanya False yang disimpan — tidak adanya kunci berarti nyala.
        if v.get("caption") is False or str(v.get("caption")).lower() in ("false", "0"):
            bersih["caption"] = False
        return bersih or None

    @field_validator("layout")
    @classmethod
    def _layout_dikenal(cls, v):
        if v is None or v == "":
            return None
        from pipeline.layout import LAYOUTS

        if v not in LAYOUTS:
            raise ValueError(f"Layout '{v}' tidak dikenal")
        return v

    @field_validator("url")
    @classmethod
    def _youtube_only(cls, v: str) -> str:
        v = v.strip()
        # Berkas yang sudah diunggah dirujuk sebagai "unggah:<uuid>". Bentuknya
        # dikunci ke UUID di unggah/ — bukan sekadar "bukan URL YouTube" —
        # karena nilai ini ikut menyusun path di disk. Yang lolos di sini TIDAK
        # PERNAH sampai ke yt-dlp: stage download bercabang lebih dulu.
        from unggah import sumber

        if sumber(v):
            return v

        # Batas kepercayaan: yang masuk sini langsung jadi argumen subprocess
        # yt-dlp. Dibatasi ke host YouTube supaya field ini tidak bisa dipakai
        # menyuruh yt-dlp mengambil URL sembarangan.
        if not any(
            v.startswith(p)
            for p in (
                "https://www.youtube.com/",
                "https://youtube.com/",
                "https://m.youtube.com/",
                "https://youtu.be/",
            )
        ):
            raise ValueError(
                "Link harus dari YouTube (youtube.com atau youtu.be). "
                "Punya berkas videonya sendiri? Pakai tab Unggah berkas."
            )
        return v


class Clip(BaseModel):
    id: str
    url: str
    duration: float
    score: int
    hook: str
    reason: str
    title: str
    caption: str
    hashtags: list[str]


class JobOut(BaseModel):
    id: str
    url: str
    target_clips: int
    layout: str = "penuh"
    gaya: dict = {}
    status: str
    progress: int
    error: str | None = None
    #: Kegagalan yang sudah diterjemahkan jadi kalimat yang bisa
    #: ditindaklanjuti: {"judul", "saran"}. Diturunkan dari `error`, bukan
    #: disimpan — job lama ikut mendapatkannya tanpa migrasi, dan teks mentahnya
    #: tetap utuh kalau terjemahannya ternyata meleset.
    masalah: dict | None = None
    clips: list[Clip] = []
    created_at: str | None = None
    updated_at: str | None = None

    @model_validator(mode="after")
    def _terjemahkan(self):
        from utils.pesan import terjemah

        if self.error and not self.masalah:
            self.masalah = terjemah(self.error)
        return self


class JobCreated(BaseModel):
    job_id: str
    status: str
