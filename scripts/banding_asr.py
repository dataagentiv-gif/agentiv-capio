"""Bandingkan dua provider transkrip pada BERKAS AUDIO YANG SAMA PERSIS.

Temuan yang jadi dasar seluruh pilihan transkrip CAPIO — 29,6% keluaran Groq
berubah jadi teks Jepang di satu dari tiga video — dulu diukur sekali lalu
hasilnya disalin manual. Sekali jalan begitu, ia anekdot: tidak bisa diulang
untuk video lain, dan tidak bisa ditunjukkan ke siapa pun tanpa memercayai
ingatan orang yang mengukurnya.

Skrip ini membuatnya bisa diulang untuk video mana pun.

Yang menentukan hasilnya bukan rata-rata akurasi, melainkan BENTUK kegagalannya:
benar di dua video lalu ambruk total di video ketiga tanpa peringatan. Karena
itu yang dilaporkan bukan satu skor, melainkan tiga hal yang masing-masing
menangkap satu bentuk kegagalan:

  non-latin   huruf di luar Latin. Whisper berpindah bahasa lalu mengarang;
              inilah yang menghasilkan 29,6% teks Jepang itu
  kemiripan   berapa banyak kata yang sama. Rendah tanpa non-latin berarti
              kalimatnya DITERJEMAHKAN, bukan ditranskrip — kegagalan yang
              tidak terlihat sama sekali dari hurufnya
  jumlah kata selisih besar berarti ada bagian yang hilang atau dikarang

Pakai:
    python scripts/banding_asr.py video.mp4
    python scripts/banding_asr.py video.mp4 --keluar banding.md
"""
import argparse
import difflib
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from asr import rasio_non_latin  # noqa: E402,F401 — dipakai laporan() dan test
from utils.ffmpeg_helpers import Deadline  # noqa: E402

# Sama persis dengan yang dipakai stage download. Membandingkan dua provider di
# atas audio yang diekstrak berbeda tidak membuktikan apa pun soal providernya.
AUDIO = ["-vn", "-ac", "1", "-ar", "16000",
         "-c:a", "libopus", "-b:a", "24k", "-vbr", "on", "-application", "voip"]


def ekstrak(sumber: Path, tujuan: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-v", "error", "-i", str(sumber),
         *AUDIO, str(tujuan)],
        check=True, timeout=1800,
    )


def kata(teks: str) -> list[str]:
    return re.findall(r"\w+", teks.lower())


def transkrip(provider: str, audio: Path) -> str:
    from config.settings import settings

    settings.ASR_PROVIDER = provider
    import asr

    words, _ = asr.transcribe(audio, 0.0)
    return " ".join(w["w"] for w in words)


def potongan_beda(a: str, b: str, n: int = 6) -> list[tuple[str, str]]:
    """Potongan yang paling berbeda, untuk ditunjukkan berdampingan.

    Inilah yang sebenarnya meyakinkan orang. Angka persentase membuat orang
    mengangguk; melihat satu kalimat Indonesia keluar sebagai aksara Jepang
    membuat mereka ingat.
    """
    ka, kb = kata(a), kata(b)
    hasil = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, ka, kb).get_opcodes():
        if tag == "equal" or (i2 - i1) < 4:
            continue
        hasil.append((" ".join(ka[i1:i2])[:160], " ".join(kb[j1:j2])[:160]))
    hasil.sort(key=lambda p: -len(p[0]))
    return hasil[:n]


def laporan(sumber: Path, hasil: dict[str, str]) -> str:
    nama = list(hasil)
    a, b = hasil[nama[0]], hasil[nama[1]]
    mirip = difflib.SequenceMatcher(None, kata(a), kata(b)).ratio() * 100

    baris = [
        f"# Perbandingan transkrip — {sumber.name}",
        "",
        "Kedua provider membaca **berkas audio yang sama persis**, diekstrak "
        "dengan setelan yang sama dengan pipeline produksi.",
        "",
        "| | " + " | ".join(nama) + " |",
        "|---|" + "---|" * len(nama),
        "| Jumlah kata | " + " | ".join(f"{len(kata(hasil[p])):,}" for p in nama) + " |",
        "| Huruf non-Latin | "
        + " | ".join(f"{rasio_non_latin(hasil[p]):.1f}%" for p in nama) + " |",
        "",
        f"**Kemiripan kata: {mirip:.1f}%**",
        "",
    ]

    tinggi = [p for p in nama if rasio_non_latin(hasil[p]) > 1]
    if tinggi:
        baris += [
            f"> **{', '.join(tinggi)} berpindah bahasa.** Huruf non-Latin di atas "
            "1% pada sumber berbahasa Indonesia berarti model berhenti "
            "mentranskrip dan mulai mengarang.",
            "",
        ]
    elif mirip < 85:
        baris += [
            "> **Kemiripan rendah tanpa huruf asing.** Ini pola penerjemahan: "
            "kalimatnya diubah maknanya, bukan disalin. Tidak terlihat sama "
            "sekali dari hurufnya — hanya dari perbandingan seperti ini.",
            "",
        ]

    beda = potongan_beda(a, b)
    if beda:
        baris += ["## Potongan yang paling berbeda", ""]
        for x, y in beda:
            baris += [f"| {nama[0]} | {nama[1]} |", "|---|---|",
                      f"| {x} | {y} |", ""]
    return "\n".join(baris)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("sumber", type=Path, help="berkas video atau audio")
    p.add_argument("--provider", nargs=2, default=["elevenlabs", "groq"])
    p.add_argument("--keluar", type=Path, help="tulis laporan Markdown ke sini")
    a = p.parse_args()

    if not a.sumber.is_file():
        print(f"Berkas tidak ada: {a.sumber}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory() as td:
        audio = Path(td) / "audio.ogg"
        print(f"Mengekstrak audio dari {a.sumber.name}…", file=sys.stderr)
        ekstrak(a.sumber, audio)

        hasil = {}
        for prov in a.provider:
            print(f"Transkrip lewat {prov}…", file=sys.stderr)
            try:
                hasil[prov] = transkrip(prov, audio)
            except Exception as e:  # noqa: BLE001
                print(f"  {prov} gagal: {e}", file=sys.stderr)
                # 403 dari Groq hampir selalu blokir IP datacenter, bukan key
                # yang salah — dan pesan aslinya ("Access denied. Please check
                # your network settings") menyuruh memeriksa hal yang benar
                # dengan cara yang membuat orang mengoprek key-nya berjam-jam.
                if "403" in str(e) and prov == "groq":
                    print(
                        "\n  Groq memblokir IP datacenter dan sebagian besar "
                        "VPN dengan 403.\n"
                        "  Key-nya kemungkinan besar tidak apa-apa. Matikan VPN "
                        "lalu ulangi\n"
                        "  perintah yang sama — perbandingan ini memang butuh "
                        "kedua provider.",
                        file=sys.stderr,
                    )
                return 2

    teks = laporan(a.sumber, hasil)
    if a.keluar:
        a.keluar.write_text(teks, encoding="utf-8")
        print(f"Laporan ditulis ke {a.keluar}", file=sys.stderr)
    else:
        print(teks)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
