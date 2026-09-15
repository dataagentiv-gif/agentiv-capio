"""Baca-tulis .env untuk halaman Settings.

Tiga aturan yang menentukan bentuk modul ini, semuanya soal keamanan:

1. Nilai rahasia TIDAK PERNAH dikirim utuh ke browser. Yang keluar cuma bentuk
   ter-mask plus penanda terisi/belum.
2. Hanya key di ALLOWLIST yang boleh ditulis. Tanpa itu, satu request POST bisa
   menyuntikkan variabel apa pun ke .env — termasuk yang dibaca proses lain.
3. DATABASE_URL dan REDIS_URL sengaja read-only. Keduanya level deployment, dan
   mengubahnya dari UI yang justru bergantung padanya adalah jebakan: salah isi
   sekali, aplikasinya mati dan halaman settings-nya ikut tidak bisa dibuka.
"""
import os
from pathlib import Path

from config.settings import ROOT, Settings, settings
from utils.logging import get

log = get(__name__)
ENV_PATH = ROOT / ".env"


def _f(key, label, group, secret=False, kind="text", help="", options=None, pool="",
       bagian="", lanjutan=False):
    """`bagian` = judul kelompok di dalam satu tab. `lanjutan` = dilipat di
    bagian "Lanjutan" yang tertutup sejak awal: setelan yang jarang perlu
    disentuh, tapi tetap harus bisa dijangkau tanpa menyunting .env."""
    return {
        "key": key, "label": label, "group": group, "secret": secret,
        "kind": kind, "help": help, "options": options or [], "pool": pool,
        "bagian": bagian, "lanjutan": lanjutan,
    }


# Satu-satunya daftar yang boleh ditulis dari UI. Urutannya = urutan tab di
# halaman Setting, dan urutan field di dalam tiap tab.
FIELDS = [
    # --- API Key ---
    #
    # Satu key Gemini buat dua tugas: mengubah suara jadi teks (menentukan
    # kualitas caption yang terbakar di video, jadi ini yang paling terasa
    # hasilnya), lalu memilih momen dan menulis judul/caption/hashtag.
    _f("GEMINI_API_KEYS", "Gemini API key", "API Key", secret=True, pool="gemini",
       help="aistudio.google.com/apikey — free tier dibatasi per PROJECT "
            "Google Cloud, bukan per key: key tambahan cuma menaikkan atap "
            "kalau dibuat di project yang berbeda. Boleh diisi beberapa, "
            "dipakai bergiliran."),
    # Urutan tier DIPAKU di llm/rute.py, tidak bisa disetel dari sini. Yang di
    # bawah ini jalan keluar untuk yang memang tahu apa yang dilakukannya —
    # kosong berarti ikut tier bawaan.
    _f("GEMINI_MODELS", "Model Gemini (timpa urutan bawaan)", "API Key", kind="multi",
       lanjutan=True,
       options=["gemini-3.5-flash", "gemini-3.5-flash-lite",
                "gemini-flash-lite-latest", "gemini-3.1-flash-lite",
                "gemini-3.7-flash"],
       help="Biarkan kosong kecuali ada alasan khusus. Urutan bawaannya sudah "
            "berjenjang: model terbaik dipakai terus di SELURUH key, dan baru "
            "turun ke model berikutnya setelah kuotanya habis di semua key. "
            "Tanda habis berumur satu jam, jadi model teratas dicoba lagi "
            "dengan sendirinya begitu kuotanya pulih — tanpa penjadwalan. "
            "Kalau diisi, daftar ini menggantikan urutan bawaan sepenuhnya."),
    _f("GEMINI_MODEL", "Model Gemini (satuan, lama)", "API Key", lanjutan=True,
       help="Hanya dipakai kalau kolom di atas kosong. Ada demi .env lama yang "
            "sudah terlanjur mengisinya. Nama berversi seperti gemini-2.5-pro "
            "dimatikan Google untuk akun baru sementara akun lama tetap bisa "
            "memakainya, jadi setelan yang disalin dari mesin lain bisa mati "
            "di sini saja."),

    # --- Lisensi ---
    _f("LICENSE_KEY", "License key", "Lisensi",
       help="Ditempel dari email pembelian, bentuknya seperti "
            "AGV-CAP-SG-K7M2QX4P. Begitu disimpan, key langsung diverifikasi ke "
            "server dan hasilnya tampil di bawah. Tanpa key, CAPIO tetap jalan "
            "normal — hanya memproses video baru yang diblokir; klip lama tetap "
            "bisa dibuka dan diunduh."),

    # --- Klip: tampilan ---
    _f("CLIP_LAYOUT", "Layout klip", "Klip", kind="select", bagian="Tampilan",
       options=["penuh", "duo", "kotak", "samping", "ori"],
       help="penuh: video mengisi layar, caption di bawah. "
            "kotak: video dalam kotak sudut tumpul di tengah, latar hitam. "
            "samping: pembicara digeser ke kiri, satu baris teks tenang di kanan. "
            "ori: rasio sumber dipertahankan dan tanpa caption — mentahan untuk "
            "diedit lagi. "
            "Ini cuma nilai AWAL di halaman Submit; layoutnya sendiri dipilih "
            "per video. Layout dipilih utuh — posisi teks dan geometri video "
            "harus sepakat."),
    _f("CAPTION_FONT", "Font caption", "Klip", kind="select", bagian="Tampilan",
       options=["Poppins", "Anton", "Archivo Black", "Lora", "DejaVu Sans"],
       help="Hanya font yang ikut dipasang di image. Nama lain tidak akan "
            "menghasilkan error — libass diam-diam menggantinya, dan yang "
            "terlihat cuma caption yang kurang mirip."),
    _f("CAPTION_SIZE", "Ukuran caption", "Klip", kind="number", bagian="Tampilan",
       help="0 = ikut bawaan layout. Kata panjang dalam Bahasa Indonesia "
            "kadang perlu dikecilkan."),
    _f("CAPTION_WORDS", "Kata per tampilan", "Klip", kind="number", bagian="Tampilan",
       help="0 = ikut bawaan layout. 1 kata besar terasa sangat beda dari 4."),
    _f("CAPTION_UPPER", "HURUF BESAR semua", "Klip", kind="select", bagian="Tampilan",
       options=["false", "true"],
       help="Lazim di klip pendek, tapi kalimat panjang jadi lebih makan ruang."),
    _f("ACTIVE_WORD_STYLE", "Gaya kata aktif", "Klip", kind="select", bagian="Tampilan",
       options=["text_color", "background", "background_scale"],
       help="text_color: cuma warna kata aktif yang berubah. background: blok "
            "berwarna bersudut tumpul di belakang kata aktif. background_scale: "
            "blok + kata aktif sedikit membesar. Ini nilai AWAL di halaman "
            "Submit; tiap video tetap bisa memilih sendiri."),
    _f("CAPTION_COLOR", "Warna kata aktif (gaya text_color)", "Klip", bagian="Tampilan",
       help="RRGGBB tanpa tanda pagar, urutan biasa seperti di CSS. "
            "Bawaan FFE500 (kuning keemasan)."),
    _f("ACTIVE_WORD_BACKGROUND_COLOR", "Warna blok", "Klip", bagian="Tampilan",
       help="RRGGBB tanpa tanda pagar. Dipakai gaya background dan background_scale."),
    _f("ACTIVE_WORD_TEXT_COLOR", "Warna teks di dalam blok", "Klip", bagian="Tampilan",
       help="RRGGBB tanpa tanda pagar. Hitam paling terbaca di atas blok terang."),
    _f("ACTIVE_WORD_BORDER_RADIUS", "Radius sudut blok (px)", "Klip", kind="number",
       bagian="Tampilan",
       help="0 = siku. Setengah tinggi blok atau lebih = pil penuh. Maksimal 60."),
    _f("ACTIVE_WORD_PADDING_X", "Padding blok kiri-kanan (px)", "Klip", kind="number",
       bagian="Tampilan", help="Jarak dari ujung kata ke tepi blok. Maksimal 60."),
    _f("ACTIVE_WORD_PADDING_Y", "Padding blok atas-bawah (px)", "Klip", kind="number",
       bagian="Tampilan", help="Jarak dari huruf ke tepi atas/bawah blok. Maksimal 60."),

    # --- Klip: batas ---
    _f("TARGET_CLIPS_DEFAULT", "Jumlah klip default", "Klip", kind="number",
       bagian="Batas klip",
       help="Nilai awal pilihan jumlah klip di halaman Submit."),
    _f("MIN_CLIP_SEC", "Durasi klip minimum (detik)", "Klip", kind="number",
       bagian="Batas klip",
       help="Momen yang lebih pendek dari ini dibuang sebelum dirender."),
    _f("MAX_CLIP_SEC", "Durasi klip maksimum (detik)", "Klip", kind="number",
       bagian="Batas klip",
       help="Momen yang lebih panjang dari ini dibuang sebelum dirender. "
            "Sesuaikan dengan platform tujuan."),
    _f("JOB_TIMEOUT_SEC", "Batas waktu per job (detik)", "Klip", kind="number",
       lanjutan=True,
       help="Job yang belum selesai setelah selama ini dihentikan dan ditandai "
            "gagal. 1800 cukup untuk video satu jam."),
    _f("SILENCE_NOISE_DB", "Ambang hening (dB)", "Klip", kind="number", lanjutan=True,
       help="-30 untuk podcast bersih. Kalau source ada musik latar, NAIKKAN "
            "ke -20 — jangan diturunkan. Musik menaikkan lantai kebisingan, "
            "jadi ambang yang lebih rendah makin mustahil tercapai: audio "
            "bermusik -24dB menghasilkan 0 jeda di -30dB, tetap 0 di -40dB, "
            "tapi 15 jeda di -20dB."),
    _f("SILENCE_MIN_DUR", "Durasi hening minimum (detik)", "Klip", kind="number",
       lanjutan=True,
       help="Jeda yang lebih pendek dari ini tidak dianggap titik potong. "
            "Naikkan ke 0.5 kalau kandidat batasnya terlalu banyak."),
    _f("SNAP_MAX_DRIFT", "Pergeseran batas maksimum (detik)", "Klip", kind="number",
       lanjutan=True,
       help="Seberapa jauh batas klip boleh digeser ke jeda alami terdekat. "
            "Kecilkan kalau batas klip terasa meleset dari momen yang dipilih."),

    # --- Kinerja ---
    _f("WORKER_MODE", "Mode worker", "Kinerja", kind="select",
       options=["single", "multi"],
       help="single (bawaan): satu job diproses sekaligus — aman untuk mesin kecil. "
            "multi: beberapa job diproses BERSAMAAN, lebih cepat kalau CPU-nya "
            "cukup — tapi tiap job menjalankan ffmpeg yang memakai SEMUA core "
            "yang ada, tanpa batas. Di mesin kecil, dua job x264 berebut core "
            "yang sama bisa membuat KEDUANYA lebih lambat daripada diproses "
            "satu-satu."),
    _f("WORKER_COUNT", "Jumlah worker (mode multi)", "Kinerja", kind="number",
       help="Berapa job diproses bersamaan saat mode di atas 'multi'. Mulai dari "
            "2 dan naikkan bertahap sambil memperhatikan beban CPU-nya."),

    # --- Infra ---
    _f("CLIPS_DIR", "Folder klip", "Infra", bagian="Penyimpanan",
       help="Klip jadi disimpan di sini sebagai file mp4 biasa — bisa dibuka, "
            "dihapus, dan disalin lewat file manager. Tidak ada storage cloud."),
    _f("WORK_DIR", "Folder kerja", "Infra", bagian="Penyimpanan",
       help="Tempat video sumber diunduh dan diolah. Sengaja pendek — path "
            "Windows mentok di 260 karakter."),
    _f("AUTO_CLEAR_ENABLED", "Bersihkan otomatis", "Infra", kind="select",
       options=["false", "true"], bagian="Auto clear",
       help="true: task dan/atau hasil yang umurnya lewat batas di bawah dibuang "
            "otomatis, dicek tiap jam. false (bawaan): tidak ada yang dihapus "
            "otomatis. Video yang sedang antre atau diproses tidak pernah disentuh."),
    _f("AUTO_CLEAR_DAYS", "Umur maksimal (hari)", "Infra", kind="number",
       bagian="Auto clear",
       help="Dihitung dari tanggal video disubmit. Contoh 30: yang disubmit lebih "
            "dari 30 hari lalu ikut dibersihkan. Kurang dari 1 dianggap mati."),
    _f("AUTO_CLEAR_TARGET", "Yang dibersihkan", "Infra", kind="select",
       options=["keduanya", "task", "hasil"], bagian="Auto clear",
       help="keduanya: job dihapus beserta semua klipnya — sama seperti tombol "
            "Hapus. task: hanya riwayat job yang tidak punya klip (gagal, atau "
            "klipnya sudah dibuang) beserta folder kerjanya; job yang masih "
            "punya klip tidak disentuh. hasil: berkas klip dibuang, tapi riwayat "
            "job tetap ada di halaman Proses."),
]

WRITABLE = {f["key"] for f in FIELDS}
KIND = {f["key"]: f["kind"] for f in FIELDS}
# Ditampilkan tapi tidak bisa diubah dari UI.
READONLY = ["DATABASE_URL", "REDIS_URL", "API_HOST", "API_PORT"]


def _kutip(v: str) -> str:
    """Bungkus tanda kutip hanya kalau perlu, supaya .env tetap enak dibaca."""
    if v and not any(c in v for c in ' \t"\'#'):
        return v
    return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _tulis_env(path: Path, values: dict) -> None:
    """Perbarui .env DI TEMPAT, tanpa mengganti filenya.

    python-dotenv.set_key menulis ke file sementara lalu os.replace. Itu gagal
    di dalam Docker: .env di-bind-mount sebagai satu file, dan menggantinya
    berarti mengganti inode-nya — kernel menolak dengan "Device or resource
    busy". Akibatnya seluruh halaman Setting tidak bisa menyimpan apa pun
    justru pada cara pemasangan yang paling disarankan.

    Menulis ulang isi file yang sama menghindari itu. Barisnya disusun penuh di
    memori lebih dulu supaya hanya ada satu operasi tulis, dan komentar serta
    urutan baris yang sudah ada tetap dipertahankan.
    """
    baris = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    sisa = dict(values)
    keluar = []
    for b in baris:
        kunci = b.split("=", 1)[0].strip() if "=" in b and not b.lstrip().startswith("#") else None
        if kunci in sisa:
            keluar.append(f"{kunci}={_kutip(sisa.pop(kunci))}")
        else:
            keluar.append(b)
    for k, v in sisa.items():
        keluar.append(f"{k}={_kutip(v)}")
    path.write_text("\n".join(keluar) + "\n", encoding="utf-8")


def mask(value: str) -> str:
    if not value:
        return ""
    return f"{value[:6]}••••••••{value[-4:]}" if len(value) > 14 else "••••••••"


def read_public() -> dict:
    """Snapshot aman untuk browser — rahasia dikirim ter-mask, bukan plaintext."""
    groups: dict[str, list] = {}
    for f in FIELDS:
        raw = str(getattr(settings, f["key"], "") or "")
        # Kolom yang punya cadangan menampilkan nilai yang BENAR-BENAR dipakai,
        # bukan isi mentahnya. Kosong di sini bukan berarti tidak ada yang
        # aktif — GEMINI_MODELS yang kosong tetap jalan lewat GEMINI_MODEL —
        # dan menampilkannya kosong membuat halaman ini menyatakan sesuatu yang
        # tidak benar tentang apa yang sedang berjalan.
        if f["key"] == "GEMINI_MODELS" and not raw:
            from llm import rute

            raw = ",".join(rute.TIER)
        groups.setdefault(f["group"], []).append(
            {**f, "value": mask(raw) if f["secret"] else raw, "filled": bool(raw)}
        )
    return {
        "groups": [{"name": n, "fields": v} for n, v in groups.items()],
        "readonly": [
            {"key": k, "value": str(getattr(settings, k, ""))} for k in READONLY
        ],
        "env_path": str(ENV_PATH),
    }


def reload() -> None:
    """Baca ulang .env ke objek settings yang sudah beredar.

    Nilai dari file ditimpakan lebih dulu ke os.environ, dan itu WAJIB:
    pydantic-settings memberi prioritas pada environment variable di atas isi
    file .env. Di Docker, compose memuat .env ke environment container saat
    start (`env_file: .env`), jadi tanpa langkah ini setiap setelan yang sudah
    terisi saat container menyala TIDAK AKAN PERNAH bisa diubah dari halaman
    Setting — tulisannya masuk ke file, aplikasinya tetap memakai nilai lama,
    dan tidak ada satu pun pesan error yang muncul.

    Hanya key yang boleh ditulis UI yang ditimpa. DATABASE_URL, REDIS_URL, dan
    kawan-kawannya sengaja dibiarkan: compose mengarahkannya ke nama service di
    dalam jaringan container, sementara .env berisi alamat localhost untuk
    pemakaian tanpa Docker. Menimpanya akan memutus koneksi database.

    Semua modul memegang referensi ke instance `settings` yang sama, jadi
    field-nya ditimpa di tempat — mengganti objeknya tidak akan terlihat oleh
    modul yang sudah mengimpornya.
    """
    from dotenv import dotenv_values

    berkas = dotenv_values(ENV_PATH)
    for k in WRITABLE:
        v = berkas.get(k)
        if v is not None:
            os.environ[k] = v

    fresh = Settings()
    for name in Settings.model_fields:
        setattr(settings, name, getattr(fresh, name))


def write(values: dict) -> list[str]:
    """Tulis nilai ke .env lalu reload. Kembalikan key yang benar-benar berubah.

    Nilai kosong DIABAIKAN, bukan ditulis. Halaman settings mengirim rahasia
    dalam bentuk ter-mask saat tidak diubah pengguna; tanpa aturan ini,
    menyimpan satu field akan menimpa seluruh key lain dengan tanda titik-titik.
    """
    ENV_PATH.touch(exist_ok=True)
    baru, changed = {}, []
    for key, value in values.items():
        if key not in WRITABLE:
            continue
        value = str(value).strip()
        if not value or "••••" in value:
            continue
        # Baris baru di dalam nilai berarti baris .env tambahan, dan itu jalan
        # pintas untuk menulis variabel apa pun tanpa lewat allowlist di atas.
        if "\n" in value or "\r" in value:
            log.warning("nilai %s memuat baris baru — ditolak", key)
            continue
        if KIND.get(key) == "number":
            # Locale Indonesia menampilkan angka desimal dengan koma, dan koma
            # yang lolos ke .env membuat pydantic gagal mem-parse float — bukan
            # cuma field itu yang rusak, tapi SELURUH konfigurasi gagal dimuat
            # dan aplikasinya tidak bisa start. Nilai yang tetap tidak masuk
            # akal dilewati, bukan ditulis mentah.
            value = value.replace(",", ".")
            try:
                float(value)
            except ValueError:
                log.warning("nilai %s bukan angka (%r) — dilewati", key, value)
                continue
        baru[key] = value
        changed.append(key)
    if changed:
        _tulis_env(ENV_PATH, baru)
        reload()
    return changed
