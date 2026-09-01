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
from dotenv import set_key

from config.settings import ROOT, Settings, settings

ENV_PATH = ROOT / ".env"


def _f(key, label, group, secret=False, kind="text", help="", options=None):
    return {
        "key": key, "label": label, "group": group, "secret": secret,
        "kind": kind, "help": help, "options": options or [],
    }


# Satu-satunya daftar yang boleh ditulis dari UI.
FIELDS = [
    _f("ASR_PROVIDER", "Provider transkrip", "Transkrip", kind="select",
       options=["groq", "elevenlabs"],
       help="groq: murah & cepat, tapi meleset di campuran Indonesia-Inggris dan menolak IP datacenter. "
            "elevenlabs: jauh lebih akurat untuk Bahasa Indonesia, berbayar per pemakaian."),
    _f("GROQ_API_KEY", "Groq API key", "Transkrip", secret=True,
       help="console.groq.com/keys — free tier 28.800 detik audio per hari."),
    _f("ELEVENLABS_API_KEY", "ElevenLabs API key", "Transkrip", secret=True,
       help="elevenlabs.io/app/settings/api-keys — dipakai hanya kalau provider di atas elevenlabs."),
    _f("ELEVENLABS_MODEL", "Model ElevenLabs", "Transkrip"),

    _f("LLM_PROVIDER", "Provider LLM", "Seleksi momen", kind="select",
       options=["openrouter", "gemini"],
       help="Dipakai untuk memilih momen dan menulis judul/caption/hashtag."),
    _f("GEMINI_API_KEYS", "Gemini API key", "Seleksi momen", secret=True,
       help="aistudio.google.com/apikey — boleh lebih dari satu dipisah koma; "
            "dipakai bergiliran karena free tier dibatasi per key."),
    _f("GEMINI_MODEL", "Model Gemini", "Seleksi momen"),
    _f("OPENROUTER_API_KEY", "OpenRouter API key", "Seleksi momen", secret=True,
       help="openrouter.ai/keys"),
    _f("OPENROUTER_MODEL", "Model OpenRouter", "Seleksi momen"),

    _f("R2_ACCOUNT_ID", "Account ID", "Storage R2", secret=True,
       help="Ada di URL dashboard Cloudflare."),
    _f("R2_ACCESS_KEY_ID", "Access Key ID", "Storage R2", secret=True,
       help="R2 > API > Manage API Tokens > Object Read & Write."),
    _f("R2_SECRET_ACCESS_KEY", "Secret Access Key", "Storage R2", secret=True,
       help="Hanya ditampilkan sekali oleh Cloudflare saat token dibuat."),
    _f("R2_BUCKET", "Nama bucket", "Storage R2"),
    _f("R2_PUBLIC_BASE_URL", "URL publik bucket", "Storage R2",
       help="Custom domain atau r2.dev, tanpa slash di akhir."),

    _f("TARGET_CLIPS_DEFAULT", "Jumlah klip default", "Guardrail", kind="number"),
    _f("MIN_CLIP_SEC", "Durasi klip minimum (detik)", "Guardrail", kind="number"),
    _f("MAX_CLIP_SEC", "Durasi klip maksimum (detik)", "Guardrail", kind="number"),
    _f("JOB_TIMEOUT_SEC", "Batas waktu per job (detik)", "Guardrail", kind="number"),

    _f("SILENCE_NOISE_DB", "Ambang hening (dB)", "Kalibrasi", kind="number",
       help="-30 untuk podcast bersih; turunkan ke -35 kalau source ada musik latar."),
    _f("SILENCE_MIN_DUR", "Durasi hening minimum (detik)", "Kalibrasi", kind="number"),
    _f("SNAP_MAX_DRIFT", "Pergeseran batas maksimum (detik)", "Kalibrasi", kind="number",
       help="Seberapa jauh batas klip boleh digeser ke jeda alami terdekat."),
    _f("WORK_DIR", "Folder kerja", "Kalibrasi",
       help="Sengaja pendek — path Windows mentok di 260 karakter."),
]

WRITABLE = {f["key"] for f in FIELDS}
# Ditampilkan tapi tidak bisa diubah dari UI.
READONLY = ["DATABASE_URL", "REDIS_URL", "API_HOST", "API_PORT"]


def mask(value: str) -> str:
    if not value:
        return ""
    return f"{value[:6]}••••••••{value[-4:]}" if len(value) > 14 else "••••••••"


def read_public() -> dict:
    """Snapshot aman untuk browser — rahasia dikirim ter-mask, bukan plaintext."""
    groups: dict[str, list] = {}
    for f in FIELDS:
        raw = str(getattr(settings, f["key"], "") or "")
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

    Semua modul memegang referensi ke instance `settings` yang sama, jadi
    field-nya ditimpa di tempat — mengganti objeknya tidak akan terlihat oleh
    modul yang sudah mengimpornya.
    """
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
    changed = []
    for key, value in values.items():
        if key not in WRITABLE:
            continue
        value = str(value).strip()
        if not value or "••••" in value:
            continue
        set_key(str(ENV_PATH), key, value)
        changed.append(key)
    if changed:
        reload()
    return changed
